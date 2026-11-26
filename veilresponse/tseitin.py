"""Tseitin encoding from hash-consed boolean ASTs to CNF.

An :class:`Encoder` owns one :class:`~veilresponse.sat.SATSolver`.  Variable 1
is reserved for the constant TRUE and asserted by a unit clause, so every gate
can be expressed over plain literals.  Nodes are encoded lazily and memoized:
because the AST is hash-consed, every shared sub-expression is encoded exactly
once per copy.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .expr import Node
from .sat import SATSolver


class Encoder:
    def __init__(self, solver: SATSolver | None = None) -> None:
        self.sat = solver or SATSolver()
        # The solver reserves index 0; the first real variable is index 1 and
        # is pinned TRUE, so FALSE is simply its negation.
        self.true_var = 1
        self.sat.new_var()
        self.sat.add_clause([self.true_var])
        self.TRUE = self.true_var
        self.FALSE = -self.true_var
        self._cache: Dict[Tuple[Node, str], int] = {}
        self._var_literals: Dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # Named booleans
    # ------------------------------------------------------------------ #
    def named_literal(self, name: str) -> int:
        """Return the literal for a named boolean (field or derived fact)."""
        lit = self._var_literals.get(name)
        if lit is None:
            lit = self.sat.new_var()
            self._var_literals[name] = lit
        return lit

    # ------------------------------------------------------------------ #
    # Gate helpers: z <=> f(inputs)
    # ------------------------------------------------------------------ #
    def gate_and(self, inputs: Sequence[int]) -> int:
        z = self.sat.new_var()
        # z = AND(inputs):
        #   z -> each input (one clause per input)
        #   all inputs together -> z
        for lit in inputs:
            self.sat.add_clause([-z, lit])
        self.sat.add_clause([*[-lit for lit in inputs], z])
        return z

    def gate_or(self, inputs: Sequence[int]) -> int:
        z = self.sat.new_var()
        # z = OR(inputs):
        #   z -> some input
        #   each input individually -> z
        self.sat.add_clause([-z, *inputs])
        for lit in inputs:
            self.sat.add_clause([-lit, z])
        return z

    def gate_xor(self, a: int, b: int) -> int:
        z = self.sat.new_var()
        # z = a XOR b, encoded as two 3-literal clauses each direction.
        self.sat.add_clause([-z, -a, -b])
        self.sat.add_clause([-z, a, b])
        self.sat.add_clause([z, -a, b])
        self.sat.add_clause([z, a, -b])
        return z

    def gate_iff(self, a: int, b: int) -> int:
        z = self.sat.new_var()
        # z = (a == b)
        self.sat.add_clause([-z, -a, b])
        self.sat.add_clause([-z, a, -b])
        self.sat.add_clause([z, -a, -b])
        self.sat.add_clause([z, a, b])
        return z

    def gate_not(self, a: int) -> int:
        return -a

    # ------------------------------------------------------------------ #
    # AST encoding
    # ------------------------------------------------------------------ #
    def encode(self, node: Node, copy: str = "x") -> int:
        """Return the literal representing ``node`` in the given copy."""
        key = (node, copy)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        kind = node.kind
        if kind == "const":
            lit = self.TRUE if node.data else self.FALSE
        elif kind == "var":
            lit = self.named_literal(f"{copy}::{node.data}")
        elif kind == "not":
            lit = -self.encode(node.data, copy)
        elif kind == "and":
            lit = self.gate_and([self.encode(c, copy) for c in node.data])
        elif kind == "or":
            lit = self.gate_or([self.encode(c, copy) for c in node.data])
        elif kind == "xor":
            a, b = node.data
            lit = self.gate_xor(self.encode(a, copy), self.encode(b, copy))
        elif kind == "iff":
            a, b = node.data
            lit = self.gate_iff(self.encode(a, copy), self.encode(b, copy))
        else:  # pragma: no cover - guarded by parser validation
            raise ValueError(f"unknown node kind {kind!r}")
        self._cache[key] = lit
        return lit

    def variable_literals(self, names: Sequence[str], copy: str) -> List[int]:
        return [self.named_literal(f"{copy}::{name}") for name in names]

    # ------------------------------------------------------------------ #
    # Structural constraints
    # ------------------------------------------------------------------ #
    def assert_equality(self, lits_x: Sequence[int], lits_y: Sequence[int]) -> None:
        """Assert each pair of literals has equal value."""
        for a, b in zip(lits_x, lits_y):
            self.sat.add_clause([-a, b])
            self.sat.add_clause([a, -b])

    def assert_strict_lex_order(
        self, xs: Sequence[int], ys: Sequence[int]
    ) -> None:
        """Assert bit vector ``xs`` is strictly lexicographically below ``ys``.

        Fields are most-significant first (the declared field order).  Let
        ``p_j`` mean "every pair before j was equal" (``p_0`` is TRUE).  At
        each position define the difference literal
        ``d_j = p_j AND NOT x_j AND y_j`` and extend the prefix with
        ``p_{j+1} = p_j AND (x_j == y_j)``.  Requiring at least one ``d_j``
        both forces an actual first difference and excludes identical
        vectors::

            exists j: p_j AND NOT x_j AND y_j
        """
        prev = self.TRUE
        difference_lits: List[int] = []
        for x, y in zip(xs, ys):
            diff_here = self.gate_and([prev, -x, y])
            difference_lits.append(diff_here)
            eq = self.gate_iff(x, y)
            prev = self.gate_and([prev, eq])
        self.sat.add_clause(difference_lits)
