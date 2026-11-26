"""Repair planning: merge returned status codes into one generic code.

A repair may only move codes listed in ``repair.merge_costs`` into a single
generic code (the default code can be made an optional merge member).  Two
records leak exactly when an audit finds indistinguishable legal records
landing on two *different* codes; merging both endpoints removes that
distinction.

Under the single-generic-code semantics the required merge set is uniquely
determined: the union of the endpoints of every conflicting code pair across
all receivers.  Every conflicting pair must have both endpoints merged, so no
proper subset works, and hence no cost tie-break is ever needed; the
sorted-code tie-break is nevertheless applied to the reported list so output
ordering stays fully deterministic.  If some endpoint is not a merge
candidate, no candidate merge set can fix the leak and a post-merge witness is
produced as evidence.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from .audit import ProductModel, Witness, check_legal_feasible
from .model import Case, code_sort_key


def _pair_key(code_a: Any, code_b: Any) -> Tuple[Any, Any]:
    return tuple(sorted((code_a, code_b), key=code_sort_key))  # type: ignore[return-value]


def collect_conflicts(case: Case) -> List[Dict[str, Any]]:
    """Re-audit every receiver against the original legal constraint."""
    per_receiver: List[Dict[str, Any]] = []
    if check_legal_feasible(case):
        for receiver in case.receivers:
            product = ProductModel(case)
            result = product.audit_receiver(receiver)
            per_receiver.append({
                "name": receiver.name,
                "leaks": result.leaks,
            })
    return per_receiver


def _post_merge_witness(
    case: Case, merged_codes: Set[Any]
) -> List[Dict[str, Any]]:
    """Witnesses that remain after merging every candidate code.

    Merging does not change which rule a record hits; it only relabels the
    returned code.  Every merged outcome reports the single generic code,
    while every non-merged outcome keeps its own code.  Two outcomes
    therefore still distinguish records after the merge exactly when they do
    not both belong to the merged set.  The product formula keeps asserting
    the original legal constraint in both copies, so each reported witness is
    re-verified against those constraints.
    """
    merged_outcomes = {
        idx
        for idx, code in enumerate(case.outcome_codes)
        if code in merged_codes
    }

    def same_effective_class(i: int, j: int) -> bool:
        return i in merged_outcomes and j in merged_outcomes

    evidence: List[Dict[str, Any]] = []
    for receiver in case.receivers:
        product = ProductModel(case)
        product.receiver_constraints(receiver)
        n = len(case.rules)
        for i in range(n + 1):
            for j in range(i + 1, n + 1):
                if same_effective_class(i, j):
                    continue
                found = product._smallest_crossing(i, j)
                if found is None:
                    continue
                rec_a, rec_b = found
                evidence.append({
                    "receiver": receiver.name,
                    "codes": sorted(
                        [case.outcome_codes[i], case.outcome_codes[j]],
                        key=code_sort_key,
                    ),
                    "effective_codes": [
                        "GENERIC" if i in merged_outcomes else case.outcome_codes[i],
                        "GENERIC" if j in merged_outcomes else case.outcome_codes[j],
                    ],
                    "record_pair": [
                        {name: rec_a[name] for name in case.fields},
                        {name: rec_b[name] for name in case.fields},
                    ],
                })
    return evidence


def plan_repair(case: Case) -> Dict[str, Any]:
    conflicts = collect_conflicts(case)

    pair_to_witnesses: Dict[Tuple[Any, Any], List[Dict[str, Any]]] = {}
    for entry in conflicts:
        for witness in entry["leaks"]:  # type: Witness
            key = _pair_key(witness.code_a, witness.code_b)
            pair_to_witnesses.setdefault(key, []).append({
                "receiver": entry["name"],
                "record_pair": [
                    {name: witness.record_a[name] for name in case.fields},
                    {name: witness.record_b[name] for name in case.fields},
                ],
            })

    if not pair_to_witnesses:
        return {
            "status": "no_repair_needed",
            "merge_codes": [],
            "total_cost": 0,
            "generic_code": "GENERIC",
            "conflicts": [],
        }

    candidate_codes = set(case.merge_candidates)
    required: Set[Any] = set()
    blockers: List[Dict[str, Any]] = []
    conflict_report: List[Dict[str, Any]] = []

    for (code_a, code_b), witnesses in sorted(
        pair_to_witnesses.items(),
        key=lambda item: tuple(code_sort_key(c) for c in item[0]),
    ):
        conflict_report.append({
            "codes": [code_a, code_b],
            "witnesses": witnesses,
        })
        required.add(code_a)
        required.add(code_b)
        missing = [c for c in (code_a, code_b) if c not in candidate_codes]
        if missing:
            blockers.append({
                "codes": [code_a, code_b],
                "non_candidate_codes": sorted(missing, key=code_sort_key),
            })

    if blockers:
        residual = _post_merge_witness(case, set(case.merge_candidates))
        return {
            "status": "unrepairable",
            "generic_code": "GENERIC",
            "blocking_conflicts": sorted(
                blockers,
                key=lambda b: tuple(code_sort_key(c) for c in b["codes"]),
            ),
            "post_merge_evidence": residual,
            "conflicts": conflict_report,
        }

    merge_codes = sorted(required, key=code_sort_key)
    total_cost = sum(case.merge_candidates[code] for code in merge_codes)
    return {
        "status": "repairable",
        "merge_codes": merge_codes,
        "total_cost": total_cost,
        "generic_code": "GENERIC",
        "conflicts": conflict_report,
    }
