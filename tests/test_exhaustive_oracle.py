import json
import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veilresponse.audit import run_audit
from veilresponse.exhaustive import exhaustive_audit, exhaustive_repair
from veilresponse.fuzzgen import random_case
from veilresponse.model import parse_case
from veilresponse.repair import plan_repair


class ExhaustiveOracleTests(unittest.TestCase):
    def test_random_cases_match_exhaustive_audit(self):
        rng = random.Random(20261127)
        trials = 120
        for trial in range(trials):
            raw = random_case(rng, max_fields=6)
            case = parse_case(raw)
            expected = exhaustive_audit(case)
            actual = run_audit(case)
            self.assertEqual(
                actual["status"], expected["status"],
                msg=f"status mismatch on {json.dumps(raw)}",
            )
            self.assertEqual(
                actual["legal_records_feasible"],
                expected["legal_records_feasible"],
            )
            self.assertEqual(len(actual["receivers"]), len(expected["receivers"]))
            for got, want in zip(actual["receivers"], expected["receivers"]):
                self.assertEqual(got["name"], want["name"])
                self.assertEqual(got["compliant"], want["compliant"])
                self.assertEqual(
                    _normalize(got["leaks"]), _normalize(want["leaks"]),
                    msg=f"witness mismatch on {json.dumps(raw)}",
                )

    def test_random_cases_match_exhaustive_repair(self):
        rng = random.Random(99)
        for _ in range(120):
            raw = random_case(rng, max_fields=6)
            case = parse_case(raw)
            expected = exhaustive_repair(case)
            actual = plan_repair(case)
            self.assertEqual(actual["status"], expected["status"])
            if expected["status"] == "repairable":
                self.assertEqual(
                    sorted(actual["merge_codes"], key=lambda c: str(c)),
                    sorted(expected["merge_codes"], key=lambda c: str(c)),
                )
                self.assertEqual(actual["total_cost"], expected["total_cost"])

    def test_scale_24_fields_does_not_enumerate_records(self):
        # 24 fields: 2^24 records must never be materialized.  The audit must
        # finish quickly through the product SAT construction alone.
        fields = [f"b{i}" for i in range(24)]
        raw = {
            "fields": fields,
            "derived_facts": {
                "parity": {"xor": ["b0", "b1"]}
            },
            "legal": True,
            "rules": [
                {"when": {"and": ["b0", {"not": "b1"}]}, "code": 1},
                {"when": "parity", "code": 2},
            ],
            "default_code": 0,
            "receivers": [
                {"name": "blind", "visible_fields": [], "derived_facts": []},
                {"name": "partial", "visible_fields": fields[2:], "derived_facts": []},
            ],
            "repair": {"merge_costs": {"0": 1, "1": 2, "2": 3}},
        }
        case = parse_case(raw)
        start = time.perf_counter()
        audit = run_audit(case)
        repair = plan_repair(case)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 20.0)
        self.assertEqual(audit["status"], "leak_detected")
        self.assertEqual(repair["status"], "repairable")


def _normalize(leaks):
    import json

    return sorted(
        (
            json.dumps(sorted(leak["codes"], key=lambda c: json.dumps(c, sort_keys=True)),
                       sort_keys=True),
            tuple(
                tuple(sorted(rec.items()))
                for rec in leak["record_pair"]
            ),
        )
        for leak in leaks
    )


if __name__ == "__main__":
    unittest.main()
