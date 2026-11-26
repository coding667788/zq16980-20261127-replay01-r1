"""Synthetic case loading, validation and the first-match rule engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .expr import Builder, Node, evaluate


@dataclass
class Rule:
    expression: Node
    code: Any
    index: int


@dataclass
class Receiver:
    name: str
    visible_fields: List[str]
    derived_facts: List[str]


@dataclass
class Case:
    fields: List[str]
    legal: Node
    rules: List[Rule]
    default_code: Any
    receivers: List[Receiver]
    derived: Dict[str, Node]
    derived_order: List[str]
    merge_candidates: Dict[Any, int]          # code -> one-time cost
    default_merge_optional: bool
    raw: Dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def outcome_codes(self) -> List[Any]:
        return [rule.code for rule in self.rules] + [self.default_code]


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ValueError(message)


def load_case(path: str | Path) -> Case:
    with open(path, "r", encoding="utf-8") as handle:
        return parse_case(json.load(handle))


def parse_case(raw: Dict[str, Any]) -> Case:
    _require(isinstance(raw, dict), "case must be a JSON object")

    fields = raw.get("fields")
    _require(
        isinstance(fields, list) and fields and all(isinstance(f, str) for f in fields),
        "'fields' must be a non-empty list of strings",
    )
    _require(len(set(fields)) == len(fields), "field names must be unique")
    _require(len(fields) <= 24, "at most 24 boolean fields are supported")

    builder = Builder()

    derived_raw = raw.get("derived_facts", {})
    _require(isinstance(derived_raw, dict), "'derived_facts' must be an object")
    # Two-phase parse: names must be declared before rule parsing so derived
    # facts may reference each other; cycles are rejected by the visited set.
    derived: Dict[str, Node] = {}
    derived_order: List[str] = []
    parsing: set[str] = set()

    def parse_named(name: str) -> Node:
        if name in derived:
            return derived[name]
        _require(name in derived_raw, f"unknown name {name!r}")
        _require(name not in parsing, f"derived fact cycle through {name!r}")
        parsing.add(name)
        node = _parse_expr(derived_raw[name])
        parsing.discard(name)
        derived[name] = node
        derived_order.append(name)
        return node

    def _parse_expr(value: Any) -> Node:
        # Builder.parse only knows variables; intercept names so derived facts
        # resolve through the two-phase lookup above.
        if isinstance(value, str):
            if value in fields:
                return builder.variable(value)
            return parse_named(value)
        if isinstance(value, bool):
            return builder.constant(value)
        if isinstance(value, dict):
            _require(len(value) == 1, "operator node needs exactly one key")
            op, raw_args = next(iter(value.items()))
            _require(op in ("not", "and", "or", "xor", "imp", "iff"),
                     f"unknown operator {op!r}")
            if op == "not":
                return builder.not_(_parse_expr(raw_args))
            _require(isinstance(raw_args, list), f"{op!r} needs a list")
            args = [_parse_expr(item) for item in raw_args]
            return builder.apply(op, args)
        raise ValueError(f"unsupported expression: {value!r}")

    for name in derived_raw:
        _require(
            isinstance(name, str) and name and name not in fields,
            f"invalid derived fact name {name!r}",
        )
    for name in derived_raw:
        parse_named(name)

    _require("legal" in raw, "case requires a 'legal' constraint")
    legal = _parse_expr(raw["legal"])

    rules_raw = raw.get("rules", [])
    _require(isinstance(rules_raw, list), "'rules' must be a list")
    rules: List[Rule] = []
    for index, item in enumerate(rules_raw):
        _require(isinstance(item, dict), f"rule {index} must be an object")
        _require("when" in item and "code" in item,
                 f"rule {index} needs 'when' and 'code'")
        rules.append(Rule(_parse_expr(item["when"]), item["code"], index))

    _require("default_code" in raw, "case requires a 'default_code'")
    default_code = raw["default_code"]

    receivers_raw = raw.get("receivers", [])
    _require(isinstance(receivers_raw, list), "'receivers' must be a list")
    receivers: List[Receiver] = []
    seen_names: set[str] = set()
    for index, item in enumerate(receivers_raw):
        _require(isinstance(item, dict), f"receiver {index} must be an object")
        name = item.get("name", f"receiver_{index}")
        _require(isinstance(name, str) and name not in seen_names,
                 f"receiver name {name!r} duplicated or invalid")
        seen_names.add(name)
        visible = item.get("visible_fields", [])
        facts = item.get("derived_facts", [])
        _require(isinstance(visible, list) and all(f in fields for f in visible),
                 f"receiver {name!r}: unknown visible field")
        _require(isinstance(facts, list) and all(f in derived for f in facts),
                 f"receiver {name!r}: unknown derived fact")
        receivers.append(Receiver(name, list(visible), list(facts)))

    repair_raw = raw.get("repair", {})
    _require(isinstance(repair_raw, dict), "'repair' must be an object")
    costs_raw = repair_raw.get("merge_costs", {})
    _require(isinstance(costs_raw, dict), "'merge_costs' must be an object")
    merge_candidates: Dict[Any, int] = {}
    known_codes = set()
    for rule in rules:
        known_codes.add(_code_key(rule.code))
    known_codes.add(_code_key(default_code))
    for key, cost in costs_raw.items():
        _require(isinstance(cost, int) and cost >= 0,
                 f"merge cost for {key!r} must be a non-negative integer")
        decoded = json.loads(key)
        _require(_code_key(decoded) in known_codes,
                 f"merge candidate {key!r} is not a returned code")
        merge_candidates[decoded] = cost

    default_optional = bool(repair_raw.get("default_code_optional", False))
    if default_optional:
        merge_candidates.setdefault(default_code, 0)

    return Case(
        fields=list(fields),
        legal=legal,
        rules=rules,
        default_code=default_code,
        receivers=receivers,
        derived=derived,
        derived_order=derived_order,
        merge_candidates=merge_candidates,
        default_merge_optional=default_optional,
        raw=raw,
    )


def _code_key(code: Any) -> str:
    """Stable hashable key for arbitrary JSON status codes."""
    return json.dumps(code, sort_keys=True, separators=(",", ":"))


def code_sort_key(code: Any) -> Tuple[int, Any]:
    """Deterministic ordering for status codes in outputs."""
    if code is None:
        return (0, 0)
    if isinstance(code, bool):
        return (1, int(code))
    if isinstance(code, (int, float)):
        return (1, code)
    if isinstance(code, str):
        return (2, code)
    return (3, _code_key(code))


def evaluate_rule_conditions(case: Case, assignment: Dict[str, bool]) -> List[bool]:
    # Derived facts may be referenced by rules; topological parse order makes
    # sure every referenced fact is already evaluated.
    values = dict(assignment)
    for name in case.derived_order:
        values[name] = evaluate(case.derived[name], values)
    return [evaluate(rule.expression, values) for rule in case.rules]


def run_engine(case: Case, assignment: Dict[str, bool]) -> Tuple[Any, int]:
    """Return (status code, outcome index); index m means the default branch."""
    conditions = evaluate_rule_conditions(case, assignment)
    for rule, holds in zip(case.rules, conditions):
        if holds:
            return rule.code, rule.index
    return case.default_code, len(case.rules)


def record_order_key(record: Dict[str, bool], fields: List[str]) -> Tuple[int, ...]:
    return tuple(1 if record[name] else 0 for name in fields)
