import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veilresponse.audit import run_audit
from veilresponse.exhaustive import exhaustive_audit
from veilresponse.model import parse_case
from veilresponse.repair import plan_repair


class SharedExpressionTests(unittest.TestCase):
    def _case(self):
        return parse_case({
            "fields": ["p", "q", "r"],
            # The same sub-expression (p OR q) is reused by a derived fact and
            # both rules, exercising hash-consing and shared Tseitin gates.
            "derived_facts": {
                "pq": {"or": ["p", "q"]},
            },
            "legal": True,
            "rules": [
                {"when": {"and": [{"or": ["p", "q"]}, "r"]}, "code": "X"},
                {"when": {"or": ["p", "q"]}, "code": "Y"},
            ],
            "default_code": "Z",
            "receivers": [
                # Sees only r and the permitted derived fact pq. Records that
                # agree on those can still differ on p/q, but pq already
                # reveals whether (p OR q) holds, so only the r boundary leaks.
                {"name": "limited", "visible_fields": ["r"], "derived_facts": ["pq"]},
                {"name": "blind", "visible_fields": [], "derived_facts": []},
            ],
            "repair": {
                "merge_costs": {"\"X\"": 1, "\"Y\"": 2, "\"Z\"": 3},
            },
        })

    def test_shared_gates_match_exhaustive_audit(self):
        case = self._case()
        actual = run_audit(case)
        expected = exhaustive_audit(case)
        self.assertEqual(actual["status"], expected["status"])
        for got, want in zip(actual["receivers"], expected["receivers"]):
            self.assertEqual(got["name"], want["name"])
            self.assertEqual(got["compliant"], want["compliant"])
            self.assertEqual(
                [(leak["codes"], leak["record_pair"]) for leak in got["leaks"]],
                [(leak["codes"], leak["record_pair"]) for leak in want["leaks"]],
            )

    def test_repair_union_endpoints(self):
        case = self._case()
        result = plan_repair(case)
        # The blind receiver distinguishes all three codes, so every code is a
        # required endpoint and the merged set is their union.
        if result["status"] == "repairable":
            required = set()
            for conflict in result["conflicts"]:
                required.update(conflict["codes"])
            self.assertEqual(set(result["merge_codes"]), required)
            self.assertEqual(
                result["total_cost"],
                sum(case.merge_candidates[c] for c in result["merge_codes"]),
            )

    def test_derived_fact_cycle_rejected(self):
        with self.assertRaises(ValueError):
            parse_case({
                "fields": ["a"],
                "derived_facts": {"d1": "d2", "d2": "d1"},
                "legal": "a",
                "rules": [],
                "default_code": 0,
                "receivers": [],
                "repair": {},
            })


if __name__ == "__main__":
    unittest.main()
