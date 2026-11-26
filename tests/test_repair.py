import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veilresponse.model import load_case
from veilresponse.repair import plan_repair

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class RepairTests(unittest.TestCase):
    def test_minimum_cost_merge_for_simple_leak(self):
        case = load_case(SAMPLES / "simple_leak.json")
        result = plan_repair(case)
        self.assertEqual(result["status"], "repairable")
        # Every conflicting endpoint must be included; costs are summed once.
        seen = set()
        for conflict in result["conflicts"]:
            seen.update(conflict["codes"])
        self.assertEqual(set(result["merge_codes"]), seen)
        expected_cost = sum(case.merge_candidates[c] for c in seen)
        self.assertEqual(result["total_cost"], expected_cost)
        # Deterministic sorted output.
        from veilresponse.model import code_sort_key
        self.assertEqual(
            result["merge_codes"],
            sorted(result["merge_codes"], key=code_sort_key),
        )

    def test_no_repair_needed_when_compliant(self):
        case = load_case(SAMPLES / "compliant.json")
        result = plan_repair(case)
        self.assertEqual(result["status"], "no_repair_needed")
        self.assertEqual(result["merge_codes"], [])
        self.assertEqual(result["total_cost"], 0)

    def test_empty_legal_set_needs_no_repair(self):
        case = load_case(SAMPLES / "empty_legal.json")
        result = plan_repair(case)
        self.assertEqual(result["status"], "no_repair_needed")

    def test_unrepairable_reports_blockers_and_post_merge_evidence(self):
        case = load_case(SAMPLES / "unrepairable.json")
        result = plan_repair(case)
        self.assertEqual(result["status"], "unrepairable")
        blocked = {
            code
            for item in result["blocking_conflicts"]
            for code in item["non_candidate_codes"]
        }
        # The default code 200 is not a merge candidate.
        self.assertIn(200, blocked)
        # After merging every available candidate, the same conflict remains.
        self.assertTrue(result["post_merge_evidence"])
        for evidence in result["post_merge_evidence"]:
            self.assertEqual(evidence["codes"], [200, 403])
            self.assertEqual(len(evidence["record_pair"]), 2)
        json.dumps(result)

    def test_default_code_optional_is_allowed_as_candidate(self):
        case = load_case(SAMPLES / "default_branch.json")
        self.assertIn(20, case.merge_candidates)
        result = plan_repair(case)
        self.assertEqual(result["status"], "repairable")
        self.assertEqual(set(result["merge_codes"]), {10, 20})

    def test_repair_rechecks_original_legal_constraint(self):
        # The repair path must use the same product formula that asserts the
        # legal constraint in both copies; an unsatisfiable legal set has no
        # conflicts to repair.
        case = load_case(SAMPLES / "empty_legal.json")
        result = plan_repair(case)
        self.assertEqual(result["status"], "no_repair_needed")


if __name__ == "__main__":
    unittest.main()
