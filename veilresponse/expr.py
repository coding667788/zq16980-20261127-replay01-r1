"""Boolean expression parsing and hash-consed AST nodes.

Expressions are pure synthetic JSON values with the following shapes::

    true | false
    "field-or-derived-name"
    {"not": expr}
    {"and": [expr, ...]}
    {"or":  [expr, ...]}
    {"xor": [expr, expr]}
    {"imp": [expr, expr]}      # implication, left -> right
    {"iff": [expr, expr]}      # logical equivalence

Nodes are hash-consed (interned) through :class:`Builder`, so syntactically
shared sub-expressions -- including facts reused by several rules -- become the
very same Python object, which later lets the SAT encoder share their Tseitin
gates.  A small amount of constant folding keeps the interned tree compact.
"""

from __future__ import annotations

from typing import Any, Dict


class Node:
    """An interned boolean expression node."""

    __slots__ = ("kind", "data", "neg")

    def __init__(self, kind: str, data: Any, neg: "Node | None" = None) -> None:
        self.kind = kind
        # kind "var"   -> field/derived name string
        # kind "const" -> bool
        # kind "not"   -> child Node
        # kind "and"/"or" -> tuple[Node, ...]
        # kind "xor"/"iff" -> tuple[Node, Node]
        self.data = data
        self.neg = neg

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Node({self.kind!r}, {self.data!r})"


class Builder:
    """Builds interned :class:`Node` trees and parses JSON expressions."""

    def __init__(self) -> None:
        self._intern: Dict[tuple, Node] = {}
        self.true = self._make("const", True)
        self.false = self._make("const", False)
        self.true.neg = self.false
        self.false.neg = self.true

    # ------------------------------------------------------------------ #
    # Core constructors
    # ------------------------------------------------------------------ #
    def _make(self, kind: str, data: Any) -> Node:
        key = (kind, data)
        node = self._intern.get(key)
        if node is None:
            node = Node(kind, data)
            self._intern[key] = node
        return node

    def variable(self, name: str) -> Node:
        if not isinstance(name, str) or not name:
            raise ValueError("variable names must be non-empty strings")
        return self._make("var", name)

    def constant(self, value: bool) -> Node:
        return self.true if value else self.false

    def not_(self, node: Node) -> Node:
        if node.kind == "const":
            return self.false if node.data else self.true
        if node.kind == "not":
            return node.data
        if node.neg is not None:
            return node.neg
        made = self._make("not", node)
        node.neg = made
        made.neg = node
        return made

    def _flatten(self, kind: str, args: tuple[Node, ...]) -> list[Node]:
        out: list[Node] = []
        for arg in args:
            if arg.kind == kind:
                out.extend(arg.data)
            else:
                out.append(arg)
        return out

    def and_(self, *args: Node) -> Node:
        flat = self._flatten("and", tuple(args))
        const = True
        kept: list[Node] = []
        seen: set[Node] = set()
        for arg in flat:
            if arg.kind == "const":
                const = const and arg.data
                if not const:
                    return self.false
                continue
            if arg not in seen:
                seen.add(arg)
                kept.append(arg)
        if not kept:
            return self.constant(const)
        if len(kept) == 1:
            return kept[0]
        return self._make("and", tuple(kept))

    def or_(self, *args: Node) -> Node:
        flat = self._flatten("or", tuple(args))
        const = False
        kept: list[Node] = []
        seen: set[Node] = set()
        for arg in flat:
            if arg.kind == "const":
                const = const or arg.data
                if const:
                    return self.true
                continue
            if arg not in seen:
                seen.add(arg)
                kept.append(arg)
        if not kept:
            return self.constant(const)
        if len(kept) == 1:
            return kept[0]
        return self._make("or", tuple(kept))

    def xor(self, left: Node, right: Node) -> Node:
        if left.kind == "const":
            return self.not_(right) if left.data else right
        if right.kind == "const":
            return self.not_(left) if right.data else left
        return self._make("xor", (left, right))

    def imp(self, left: Node, right: Node) -> Node:
        # a -> b  ==  !a or b
        return self.or_(self.not_(left), right)

    def iff(self, left: Node, right: Node) -> Node:
        if left.kind == "const":
            return right if left.data else self.not_(right)
        if right.kind == "const":
            return left if right.data else self.not_(left)
        return self._make("iff", (left, right))

    def apply(self, op: str, args: list[Node]) -> Node:
        if op == "and":
            return self.and_(*args)
        if op == "or":
            return self.or_(*args)
        if op in ("xor", "iff"):
            if len(args) != 2:
                raise ValueError(f"{op!r} expects exactly 2 operands")
            return self.xor(*args) if op == "xor" else self.iff(*args)
        if op == "imp":
            if len(args) != 2:
                raise ValueError("'imp' expects exactly 2 operands")
            return self.imp(*args)
        raise ValueError(f"unknown operator {op!r}")

    # ------------------------------------------------------------------ #
    # JSON parsing
    # ------------------------------------------------------------------ #
    def parse(self, value: Any) -> Node:
        if isinstance(value, bool):
            return self.constant(value)
        if isinstance(value, str):
            return self.variable(value)
        if isinstance(value, dict):
            if "not" in value:
                if len(value) != 1:
                    raise ValueError("'not' node must contain only the 'not' key")
                return self.not_(self.parse(value["not"]))
            if len(value) != 1:
                raise ValueError("operator node must contain exactly one operator key")
            op, raw_args = next(iter(value.items()))
            if op not in ("and", "or", "xor", "imp", "iff"):
                raise ValueError(f"unknown operator {op!r}")
            if not isinstance(raw_args, list):
                raise ValueError(f"{op!r} requires a list of operands")
            return self.apply(op, [self.parse(item) for item in raw_args])
        raise ValueError(f"unsupported expression: {value!r}")


def evaluate(node: Node, assignment: Dict[str, bool]) -> bool:
    """Evaluate a parsed expression against a named boolean assignment."""
    kind = node.kind
    if kind == "const":
        return bool(node.data)
    if kind == "var":
        try:
            return bool(assignment[node.data])
        except KeyError as exc:
            raise ValueError(f"unbound variable {node.data!r}") from exc
    if kind == "not":
        return not evaluate(node.data, assignment)
    if kind == "and":
        return all(evaluate(child, assignment) for child in node.data)
    if kind == "or":
        return any(evaluate(child, assignment) for child in node.data)
    if kind == "xor":
        a, b = node.data
        return evaluate(a, assignment) != evaluate(b, assignment)
    if kind == "iff":
        a, b = node.data
        return evaluate(a, assignment) == evaluate(b, assignment)
    raise ValueError(f"unknown node kind {kind!r}")  # pragma: no cover
