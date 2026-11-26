"""Independent exhaustive reference for cases with at most 8 boolean fields.

This module deliberately re-implements the audit and repair logic by
enumerating every assignment (at most 256), evaluating the parsed AST with the
tree-walking evaluator, and pairing legal records directly.  It shares no code
with the SAT-based product construction, which makes it a genuine oracle in
the unittest fuzz suite.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Tuple

from .expr import evaluate
from .model import Case, Receiver, code_sort_key, record_order_key, run_engine


MAX_EXHAUSTIVE_FIELDS = 8


def enumerate_legal_records(case: Case) -> List[Dict[str, bool]]:
    if len(case.fields) > MAX_EXHAUSTIVE_FIELDS:
        raise ValueError(
            f"exhaustive reference supports at most {MAX_EXHAUSTIVE_FIELDS} fields"
        )
    legal_records: List[Dict[str, bool]] = []
    for bits in itertools.product((False, True), repeat=len(case.fields)):
        record = dict(zip(case.fields, bits))
        if evaluate(case.legal, record):
            legal_records.append(record)
    legal_records.sort(key=lambda r: record_order_key(r, case.fields))
    return legal_records


def _visible_key(
    case: Case, receiver: Receiver, record: Dict[str, bool], derived_values: Dict[str, bool]
) -> Tuple[Tuple[bool, ...], Tuple[bool, ...]]:
    visible = tuple(record[name] for name in receiver.visible_fields)
    facts = tuple(derived_values[name] for name in receiver.derived_facts)
    return visible, facts


def _derived_values(case: Case, record: Dict[str, bool]) -> Dict[str, bool]:
    values = dict(record)
    for name in case.derived_order:
        values[name] = evaluate(case.derived[name], values)
    return values


def exhaustive_audit(case: Case) -> Dict[str, Any]:
    legal_records = enumerate_legal_records(case)
    receivers_out: List[Dict[str, Any]] = []
    compliant = True

    for receiver in case.receivers:
        buckets: Dict[Tuple[Any, ...], List[Tuple[Dict[str, bool], Any]]] = {}
        derived_cache = {
            id(record): _derived_values(case, record) for record in legal_records
        }
        for record in legal_records:
            derived = derived_cache[id(record)]
            code, _ = run_engine(case, record)
            key = _visible_key(case, receiver, record, derived)
            buckets.setdefault(key, []).append((record, code))

        # One lexicographically smallest record pair per distinct code pair.
        best_by_codes: Dict[Tuple[Any, Any], Tuple[Dict[str, bool], Dict[str, bool]]] = {}
        for equivalents in buckets.values():
            for idx in range(len(equivalents)):
                for jdx in range(idx + 1, len(equivalents)):
                    rec_a, code_a = equivalents[idx]
                    rec_b, code_b = equivalents[jdx]
                    if code_sort_key(code_a) == code_sort_key(code_b):
                        continue
                    code_pair = tuple(sorted((code_a, code_b), key=code_sort_key))
                    pair = tuple(sorted(
                        (rec_a, rec_b),
                        key=lambda r: record_order_key(r, case.fields),
                    ))
                    incumbent = best_by_codes.get(code_pair)
                    if incumbent is None or tuple(
                        record_order_key(r, case.fields) for r in pair
                    ) < tuple(
                        record_order_key(r, case.fields) for r in incumbent
                    ):
                        best_by_codes[code_pair] = pair  # type: ignore[assignment]

        leaks: List[Dict[str, Any]] = [
            {
                "codes": list(code_pair),
                "record_pair": [
                    {name: rec[name] for name in case.fields}
                    for rec in best_by_codes[code_pair]
                ],
            }
            for code_pair in sorted(
                best_by_codes, key=lambda cp: tuple(code_sort_key(c) for c in cp)
            )
        ]
        if leaks:
            compliant = False
        receivers_out.append({"name": receiver.name, "compliant": not leaks, "leaks": leaks})

    return {
        "status": "compliant" if compliant else "leak_detected",
        "legal_records_feasible": bool(legal_records),
        "receivers": receivers_out,
    }


def exhaustive_repair(case: Case) -> Dict[str, Any]:
    """Exhaustive repair oracle using the same single-generic-code semantics."""
    legal_records = enumerate_legal_records(case)
    pair_witnesses: Dict[Tuple[Any, Any], List[Dict[str, Any]]] = {}

    for receiver in case.receivers:
        buckets: Dict[Tuple[Any, ...], List[Tuple[Dict[str, bool], Any]]] = {}
        for record in legal_records:
            derived = _derived_values(case, record)
            code, _ = run_engine(case, record)
            key = _visible_key(case, receiver, record, derived)
            buckets.setdefault(key, []).append((record, code))
        for equivalents in buckets.values():
            for idx in range(len(equivalents)):
                for jdx in range(idx + 1, len(equivalents)):
                    rec_a, code_a = equivalents[idx]
                    rec_b, code_b = equivalents[jdx]
                    if code_sort_key(code_a) == code_sort_key(code_b):
                        continue
                    pair_key = tuple(sorted((code_a, code_b), key=code_sort_key))
                    pair = sorted(
                        (rec_a, rec_b),
                        key=lambda r: record_order_key(r, case.fields),
                    )
                    pair_witnesses.setdefault(pair_key, []).append({  # type: ignore[arg-type]
                        "receiver": receiver.name,
                        "record_pair": [
                            {name: pair[0][name] for name in case.fields},
                            {name: pair[1][name] for name in case.fields},
                        ],
                    })

    if not pair_witnesses:
        return {"status": "no_repair_needed", "merge_codes": [], "total_cost": 0}

    required: Set[Any] = set()
    for code_a, code_b in pair_witnesses:
        required.add(code_a)
        required.add(code_b)
    candidates = set(case.merge_candidates)
    if not required <= candidates:
        return {
            "status": "unrepairable",
            "non_candidate_codes": sorted(required - candidates, key=code_sort_key),
        }
    merge_codes = sorted(required, key=code_sort_key)
    return {
        "status": "repairable",
        "merge_codes": merge_codes,
        "total_cost": sum(case.merge_candidates[code] for code in merge_codes),
    }
