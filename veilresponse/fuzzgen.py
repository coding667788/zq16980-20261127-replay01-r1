"""Random synthetic case generation for fuzz tests (no external data)."""

from __future__ import annotations

import random
from typing import Any, Dict, List


OPERATORS = ("and", "or", "xor", "imp", "iff", "not")


def random_expr(rng: random.Random, names: List[str], depth: int) -> Dict[str, Any]:
    if depth <= 0 or rng.random() < 0.35:
        if rng.random() < 0.1:
            return rng.choice([True, False])
        return rng.choice(names)
    op = rng.choice(OPERATORS)
    if op == "not":
        return {"not": random_expr(rng, names, depth - 1)}
    if op in ("xor", "imp", "iff"):
        return {op: [random_expr(rng, names, depth - 1),
                     random_expr(rng, names, depth - 1)]}
    size = rng.randint(2, 3)
    return {op: [random_expr(rng, names, depth - 1) for _ in range(size)]}


def random_case(rng: random.Random, max_fields: int = 6) -> Dict[str, Any]:
    n = rng.randint(2, max_fields)
    fields = [f"f{i}" for i in range(n)]

    derived: Dict[str, Any] = {}
    for d in range(rng.randint(0, 2)):
        name = f"d{d}"
        derived[name] = random_expr(rng, fields + list(derived), rng.randint(1, 3))

    legal = random_expr(rng, fields + list(derived), rng.randint(1, 3))
    rule_count = rng.randint(1, 4)
    rules = [
        {
            "when": random_expr(rng, fields + list(derived), rng.randint(1, 3)),
            "code": rng.choice([100, 200, 300, "A", "B"]),
        }
        for _ in range(rule_count)
    ]
    default_code = rng.choice([0, 404, "D"])

    receivers = []
    all_facts = list(derived)
    for r in range(rng.randint(1, 3)):
        receivers.append({
            "name": f"rcv{r}",
            "visible_fields": rng.sample(fields, rng.randint(0, n)),
            "derived_facts": rng.sample(all_facts, rng.randint(0, len(all_facts))),
        })

    returned = {rule["code"] for rule in rules} | {default_code}
    costs = {}
    for code in sorted(returned, key=lambda c: str(c)):
        if rng.random() < 0.7:
            costs[code_key(code)] = rng.randint(1, 9)
    repair: Dict[str, Any] = {"merge_costs": costs}
    if rng.random() < 0.5:
        repair["default_code_optional"] = True
        costs.setdefault(code_key(default_code), rng.randint(1, 5))

    return {
        "fields": fields,
        "derived_facts": derived,
        "legal": legal,
        "rules": rules,
        "default_code": default_code,
        "receivers": receivers,
        "repair": repair,
    }


def code_key(code: Any) -> str:
    import json

    return json.dumps(code, sort_keys=True, separators=(",", ":"))
