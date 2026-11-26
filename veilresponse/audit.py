"""Indirect leakage audit via a two-copy product SAT construction.

For one receiver we build a formula over two legal records ``x`` and ``y``:

* every field/expression gate is Tseitin-encoded twice (copies "x"/"y");
* the original ``legal`` constraint is asserted in **both** copies, so the
  audit and every later repair re-check the original legality constraints;
* fields visible to the receiver, plus exactly the derived facts the receiver
  is allowed to see, are constrained equal between the copies;
* a strict lexicographic order on the declared field sequence removes the
  symmetric (x, y) / (y, x) duplicate;
* first-match outcome variables ``hit_i`` encode the rule engine, including
  the default branch, and are mutually exclusive and exhaustive.

A leak between outcomes ``i`` and ``j`` then reduces to one SAT query
(``hit_i(x) AND hit_j(y)``).  Nothing ever enumerates the 2^24 records or the
quadratic set of record pairs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .model import Case, Receiver, code_sort_key, record_order_key
from .sat import SATSolver
from .tseitin import Encoder


@dataclass
class Witness:
    code_a: Any
    code_b: Any
    record_a: Dict[str, bool]
    record_b: Dict[str, bool]


@dataclass
class ReceiverAudit:
    name: str
    feasible: bool
    leaks: List[Witness]


class ProductModel:
    """The shared two-copy formula plus per-receiver equality constraints."""

    def __init__(self, case: Case) -> None:
        self.case = case
        self.encoder = Encoder(SATSolver())
        enc = self.encoder
        sat = enc.sat
        n = len(case.rules)
        m_outcomes = n + 1

        # 1. Field variables for both copies.
        self.x_vars = enc.variable_literals(case.fields, "x")
        self.y_vars = enc.variable_literals(case.fields, "y")

        # 2. Original legal constraint, re-checked in every copy.
        sat.add_clause([enc.encode(case.legal, "x")])
        sat.add_clause([enc.encode(case.legal, "y")])

        # 3. First-match outcome semantics.
        self._build_outcomes(n)

        # 4. Rule-engine outcomes are mutually exclusive and exhaustive.
        for i in range(m_outcomes):
            for j in range(i + 1, m_outcomes):
                sat.add_clause([-self.hit_x[i], -self.hit_x[j]])
                sat.add_clause([-self.hit_y[i], -self.hit_y[j]])
        sat.add_clause(list(self.hit_x))
        sat.add_clause(list(self.hit_y))

        # 5. Rule out the symmetric duplicate up front: x < y lexicographically.
        enc.assert_strict_lex_order(self.x_vars, self.y_vars)

        # 6. Crossing gates z_ij <=> hit_i(x) AND hit_j(y) for every ordered
        # outcome pair.  Strict lex order only constrains the field vectors,
        # not the outcome indices, so x may land on a higher-index outcome
        # than y and both orientations must be queryable.
        self.cross: Dict[Tuple[int, int], int] = {}
        for i in range(m_outcomes):
            for j in range(m_outcomes):
                self.cross[(i, j)] = enc.gate_and([self.hit_x[i], self.hit_y[j]])

    # ------------------------------------------------------------------ #
    def _build_outcomes(self, n: int) -> None:
        enc = self.encoder
        sat = enc.sat
        self.rule_x: List[int] = []
        self.rule_y: List[int] = []
        for rule in self.case.rules:
            self.rule_x.append(enc.encode(rule.expression, "x"))
            self.rule_y.append(enc.encode(rule.expression, "y"))

        self.hit_x: List[int] = []
        self.hit_y: List[int] = []
        prefix_x: List[int] = []
        prefix_y: List[int] = []
        for i in range(n):
            # First match: rule i holds and no earlier rule held.
            hx = enc.gate_and([self.rule_x[i], *[-r for r in prefix_x]])
            hy = enc.gate_and([self.rule_y[i], *[-r for r in prefix_y]])
            self.hit_x.append(hx)
            self.hit_y.append(hy)
            prefix_x.append(self.rule_x[i])
            prefix_y.append(self.rule_y[i])
        # Default branch: no rule fired.
        self.hit_x.append(enc.gate_and([-r for r in self.rule_x]) if self.rule_x else enc.TRUE)
        self.hit_y.append(enc.gate_and([-r for r in self.rule_y]) if self.rule_y else enc.TRUE)

    # ------------------------------------------------------------------ #
    def receiver_constraints(self, receiver: Receiver) -> None:
        """Assert visible-field and permitted derived-fact equality."""
        enc = self.encoder
        for name in receiver.visible_fields:
            idx = self.case.fields.index(name)
            enc.assert_equality([self.x_vars[idx]], [self.y_vars[idx]])
        for name in receiver.derived_facts:
            node = self.case.derived[name]
            enc.assert_equality([enc.encode(node, "x")], [enc.encode(node, "y")])

    # ------------------------------------------------------------------ #
    def _record_from_model(self, model: Sequence[int], copy_vars: Sequence[int]) -> Dict[str, bool]:
        values = {abs(lit): lit > 0 for lit in model}
        return {
            name: bool(values[var])
            for name, var in zip(self.case.fields, copy_vars)
        }

    def lex_min_witness(self, crossing_lit: int) -> Optional[Tuple[Dict[str, bool], Dict[str, bool]]]:
        """Find the lexicographically smallest record pair satisfying ``lit``.

        The formula already asserts strict field-order lexicographic order
        ``x < y``, which removes the symmetric duplicate.  To obtain the
        smallest *pair* we minimize bit vectors in field order, record x
        first and record y second: at every bit, force FALSE while the
        resulting assumptions stay satisfiable, otherwise fix TRUE.  Only
        still-open variables are decided, so propagation-derived values are
        never contradicted.
        """
        sat = self.encoder.sat
        base = [crossing_lit]
        if sat.solve(list(base)) is None:
            return None
        assumptions: List[int] = list(base)
        ordered_vars = [*self.x_vars, *self.y_vars]
        for var in ordered_vars:
            if sat.solve([*assumptions, -var]) is not None:
                assumptions.append(-var)
            else:
                assumptions.append(var)
        model = sat.solve(list(assumptions))
        assert model is not None
        record_x = self._record_from_model(model, self.x_vars)
        record_y = self._record_from_model(model, self.y_vars)
        return record_x, record_y

    # ------------------------------------------------------------------ #
    def audit_receiver(self, receiver: Receiver) -> ReceiverAudit:
        self.receiver_constraints(receiver)
        n = len(self.case.rules)
        # Keyed by status-code pair: distinct outcomes that return the same
        # code describe one observable distinction, and only the
        # lexicographically smallest witness for each code pair is reported.
        best_by_codes: Dict[Tuple[Any, Any], Witness] = {}
        for i in range(n + 1):
            for j in range(i + 1, n + 1):
                code_pair = tuple(
                    sorted(
                        (self.case.outcome_codes[i], self.case.outcome_codes[j]),
                        key=code_sort_key,
                    )
                )
                # The receiver observes codes, not rule indices: identical
                # codes cannot leak regardless of which rule fired.
                if code_sort_key(code_pair[0]) == code_sort_key(code_pair[1]):
                    continue
                witness = self._smallest_crossing(i, j)
                if witness is None:
                    continue
                rec_a, rec_b = witness
                candidate = Witness(code_pair[0], code_pair[1], rec_a, rec_b)
                incumbent = best_by_codes.get(code_pair)
                if incumbent is None or self._witness_key(candidate) < self._witness_key(incumbent):
                    best_by_codes[code_pair] = candidate
        leaks = [
            best_by_codes[key]
            for key in sorted(
                best_by_codes, key=lambda cp: tuple(code_sort_key(c) for c in cp)
            )
        ]
        return ReceiverAudit(receiver.name, feasible=True, leaks=leaks)

    def _witness_key(self, witness: Witness) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
        return (
            record_order_key(witness.record_a, self.case.fields),
            record_order_key(witness.record_b, self.case.fields),
        )

    def _smallest_crossing(
        self, i: int, j: int
    ) -> Optional[Tuple[Dict[str, bool], Dict[str, bool]]]:
        """Lexicographically smallest witness for outcomes i and j in either order."""
        candidates = []
        for crossing in (self.cross[(i, j)], self.cross[(j, i)]):
            found = self.lex_min_witness(crossing)
            if found is not None:
                candidates.append(found)
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda pair: tuple(
                record_order_key(record, self.case.fields) for record in pair
            ),
        )


def check_legal_feasible(case: Case) -> bool:
    """Single-copy SAT check: does the legal set contain any record at all?"""
    enc = Encoder(SATSolver())
    vars_ = enc.variable_literals(case.fields, "x")
    enc.sat.add_clause([enc.encode(case.legal, "x")])
    return enc.sat.solve() is not None


def check_rule_feasible(case: Case) -> List[bool]:
    """Which rules have any satisfying legal assignment at all."""
    enc = Encoder(SATSolver())
    enc.variable_literals(case.fields, "x")
    enc.sat.add_clause([enc.encode(case.legal, "x")])
    result: List[bool] = []
    for rule in case.rules:
        lit = enc.encode(rule.expression, "x")
        result.append(enc.sat.solve([lit]) is not None)
    return result


def check_rule_shadowed(case: Case) -> List[bool]:
    """Which rules can never fire because an earlier rule always fires first."""
    enc = Encoder(SATSolver())
    enc.variable_literals(case.fields, "x")
    enc.sat.add_clause([enc.encode(case.legal, "x")])
    earlier: List[int] = []
    shadowed: List[bool] = []
    for rule in case.rules:
        lit = enc.encode(rule.expression, "x")
        # Fires only when the rule holds while every earlier rule is false.
        assumptions = [lit, *[-r for r in earlier]]
        shadowed.append(enc.sat.solve(assumptions) is None)
        earlier.append(lit)
    return shadowed


def run_audit(case: Case) -> Dict[str, Any]:
    """Full audit result as JSON-serializable dictionaries."""
    feasible = check_legal_feasible(case)
    rule_feasible = check_rule_feasible(case)
    rule_shadowed = check_rule_shadowed(case)

    diagnostics = []
    for rule, can_hold, is_shadow in zip(case.rules, rule_feasible, rule_shadowed):
        diagnostics.append({
            "rule_index": rule.index,
            "code": rule.code,
            "has_feasible_assignment": can_hold,
            "shadowed_by_earlier_rule": is_shadow,
            "can_fire": can_hold and not is_shadow,
        })

    receiver_results: List[Dict[str, Any]] = []
    compliant = True
    if feasible:
        for receiver in case.receivers:
            model = ProductModel(case)
            result = model.audit_receiver(receiver)
            entry = {
                "name": result.name,
                "compliant": not result.leaks,
                "leaks": [_witness_dict(case, w) for w in result.leaks],
            }
            receiver_results.append(entry)
            if result.leaks:
                compliant = False
    else:
        # Empty legal record set: no two records exist, so every receiver
        # vacuously passes; diagnostics are still reported.
        for receiver in case.receivers:
            receiver_results.append({
                "name": receiver.name,
                "compliant": True,
                "leaks": [],
            })

    return {
        "status": "compliant" if compliant else "leak_detected",
        "legal_records_feasible": feasible,
        "rule_diagnostics": diagnostics,
        "receivers": receiver_results,
    }


def _witness_dict(case: Case, witness: Witness) -> Dict[str, Any]:
    return {
        "codes": sorted([witness.code_a, witness.code_b], key=code_sort_key),
        "record_pair": [
            _ordered_record(case, witness.record_a),
            _ordered_record(case, witness.record_b),
        ],
    }


def _ordered_record(case: Case, record: Dict[str, bool]) -> Dict[str, bool]:
    return {name: record[name] for name in case.fields}
