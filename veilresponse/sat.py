"""A small self-contained DPLL SAT solver.

Only the Python standard library is used.  Clauses are tuples of signed
integers: variable ``v`` is literal ``+v`` and its negation is ``-v``;
variable 0 never exists.

The implementation deliberately favors correctness over micro-optimization.
Clause state is recomputed from the current assignment trail:

* after each enqueue, only clauses mentioning the assigned variable are
  reclassified (satisfied / unassigned count / conflict / unit);
* on backtrack the partial trail is replayed from scratch to rebuild the
  exact clause state, which removes an entire class of undo-stack bugs.

The product constructions audited here contain on the order of a few hundred
small clauses, so the replay cost is negligible.
"""

from __future__ import annotations

from typing import List, Optional, Sequence


class SATSolver:
    def __init__(self) -> None:
        self.clauses: List[tuple[int, ...]] = []
        self.occurrences: List[List[tuple[int, int]]] = [[]]  # (literal, cid)
        self.value: List[int] = [0]   # -1 false, 0 open, 1 true
        self.trail: List[int] = []
        self.decision_at: List[int] = []
        self._clause_unassigned: List[int] = []
        self._clause_satisfied: List[bool] = []
        self._qhead = 0

    # ------------------------------------------------------------------ #
    # Formula construction
    # ------------------------------------------------------------------ #
    def new_var(self) -> int:
        var = len(self.value)
        self.value.append(0)
        self.occurrences.append([])
        return var

    def add_clause(self, literals: Sequence[int]) -> None:
        uniq = set(literals)
        if any((-lit) in uniq for lit in uniq):
            return  # tautology
        clause = tuple(uniq)
        cid = len(self.clauses)
        self.clauses.append(clause)
        self._clause_unassigned.append(len(clause))
        self._clause_satisfied.append(False)
        for lit in clause:
            v = abs(lit)
            while v >= len(self.occurrences):
                self.occurrences.append([])
                self.value.append(0)
            self.occurrences[v].append((lit, cid))

    # ------------------------------------------------------------------ #
    # Assignment bookkeeping
    # ------------------------------------------------------------------ #
    def _lit_value(self, lit: int) -> int:
        v = self.value[abs(lit)]
        if v == 0:
            return 0
        return v if lit > 0 else -v

    def _classify_clause(self, cid: int) -> None:
        unassigned = 0
        satisfied = False
        for cand in self.clauses[cid]:
            cand_value = self._lit_value(cand)
            if cand_value == 1:
                satisfied = True
            elif cand_value == 0:
                unassigned += 1
        self._clause_unassigned[cid] = unassigned
        self._clause_satisfied[cid] = satisfied

    def _enqueue(self, lit: int) -> bool:
        """Assign ``lit``; return False if it contradicts a current assignment."""
        v = abs(lit)
        if self.value[v] != 0:
            return self._lit_value(lit) == 1
        self.value[v] = 1 if lit > 0 else -1
        self.trail.append(lit)
        # Reclassify only clauses mentioning v.  Each such clause is
        # recomputed from all its literals (not incrementally), which stays
        # correct when a clause contains both polarities of v or loses a
        # satisfying literal as another variable gets assigned.
        touched = {cid for _used_lit, cid in self.occurrences[v]}
        for cid in touched:
            self._classify_clause(cid)
        return True

    def _rebuild_from_trail(self, keep: int) -> None:
        """Recompute all clause state from the first ``keep`` trail literals."""
        dropped = self.trail[keep:]
        for lit in dropped:
            self.value[abs(lit)] = 0
        del self.trail[keep:]
        for cid, clause in enumerate(self.clauses):
            self._clause_unassigned[cid] = len(clause)
            self._clause_satisfied[cid] = False
        for lit in self.trail:
            for _used_lit, cid in self.occurrences[abs(lit)]:
                self._classify_clause(cid)
        self._qhead = len(self.trail)

    def _hard_reset(self) -> None:
        """Undo every assignment, including root-level literals."""
        for lit in self.trail:
            self.value[abs(lit)] = 0
        self.trail.clear()
        self.decision_at.clear()
        self._qhead = 0
        for cid, clause in enumerate(self.clauses):
            self._clause_unassigned[cid] = len(clause)
            self._clause_satisfied[cid] = False

    def _backtrack_to(self, level: int) -> None:
        mark = self.decision_at[level]
        self.decision_at = self.decision_at[:level]
        self._rebuild_from_trail(mark)

    # ------------------------------------------------------------------ #
    # Propagation
    # ------------------------------------------------------------------ #
    def _propagate(self) -> Optional[int]:
        """Unit propagation; returns a conflicting clause id or None."""
        while self._qhead < len(self.trail):
            lit = self.trail[self._qhead]
            self._qhead += 1
            touched = {cid for _used, cid in self.occurrences[abs(lit)]}
            for cid in touched:
                if self._clause_satisfied[cid]:
                    continue
                if self._clause_unassigned[cid] == 0:
                    return cid
                if self._clause_unassigned[cid] == 1:
                    unit: Optional[int] = None
                    for cand in self.clauses[cid]:
                        if self._lit_value(cand) == 0:
                            unit = cand
                            break
                    if unit is None:  # pragma: no cover - guarded by counts
                        return cid
                    if not self._enqueue(unit):
                        return cid
        return None

    def _root_sweep(self, assumptions: Sequence[int]) -> bool:
        """Apply structural units, assumptions and derived units.

        Returns True if a root-level conflict makes the formula UNSAT under
        these assumptions.  Structural unit clauses (such as the reserved
        TRUE variable) are enqueued before assumptions, otherwise gate
        literals built from TRUE/FALSE stay unclassified while assumptions
        are processed.
        """
        # Phase 1: structural units from the formula itself, to a fixpoint.
        for _ in range(len(self.clauses) + 1):
            progressed = False
            for cid, clause in enumerate(self.clauses):
                if self._clause_satisfied[cid]:
                    continue
                if self._clause_unassigned[cid] == 0:
                    return True
                if self._clause_unassigned[cid] == 1:
                    unit = next(
                        (cand for cand in clause if self._lit_value(cand) == 0),
                        None,
                    )
                    if unit is None:  # pragma: no cover - guarded by counts
                        return True
                    if not self._enqueue(unit):
                        return True
                    progressed = True
            if not progressed:
                break
        if self._propagate() is not None:
            return True

        # Phase 2: caller assumptions.
        for lit in assumptions:
            cur = self._lit_value(lit)
            if cur == -1:
                return True
            if cur == 0 and not self._enqueue(lit):
                return True

        # Phase 3: units/conflicts implied by the assumptions.
        for _ in range(len(self.clauses) + 1):
            conflict = self._propagate()
            if conflict is not None:
                return True
            progressed = False
            for cid, clause in enumerate(self.clauses):
                if self._clause_satisfied[cid]:
                    continue
                if self._clause_unassigned[cid] == 0:
                    return True
                if self._clause_unassigned[cid] == 1:
                    unit = next(
                        (cand for cand in clause if self._lit_value(cand) == 0),
                        None,
                    )
                    if unit is None:  # pragma: no cover - guarded by counts
                        return True
                    if not self._enqueue(unit):
                        return True
                    progressed = True
            if not progressed:
                return False
        return False  # pragma: no cover - sweep bound is conservative

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #
    def solve(self, assumptions: Sequence[int] = ()) -> Optional[List[int]]:
        """Return a full model (signed literals) or None for UNSAT."""
        self._hard_reset()
        if self._root_sweep(list(assumptions)):
            self._hard_reset()
            return None

        order = sorted(
            range(1, len(self.value)),
            key=lambda v: (-len(self.occurrences[v]), v),
        )
        while True:
            conflict = self._propagate()
            if conflict is not None:
                if not self.decision_at:
                    self._hard_reset()
                    return None
                level = len(self.decision_at) - 1
                decision = self.trail[self.decision_at[level]]
                self._backtrack_to(level)
                if not self._enqueue(-decision):
                    self._hard_reset()
                    return None
                if self._propagate() is not None:
                    continue
                continue

            branch = next((v for v in order if self.value[v] == 0), None)
            if branch is None:
                model = [
                    v if self.value[v] == 1 else -v
                    for v in range(1, len(self.value))
                ]
                self._hard_reset()
                return model
            self.decision_at.append(len(self.trail))
            self._enqueue(branch)

    def is_satisfiable(self, assumptions: Sequence[int] = ()) -> bool:
        return self.solve(list(assumptions)) is not None
