import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veilresponse.audit import run_audit
from veilresponse.model import load_case
from veilresponse.exhaustive import enumerate_legal_records, exhaustive_audit

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class SampleAuditTests(unittest.TestCase):
    def test_simple_leak_detects_and_witness_is_lex_min(self):
        case = load_case(SAMPLES / "simple_leak.json")
        result = run_audit(case)
        self.assertEqual(result["status"], "leak_detected")
        ops = next(r for r in result["receivers"] if r["name"] == "ops")
        self.assertFalse(ops["compliant"])
        leak = ops["leaks"][0]
        pair = leak["record_pair"]
        # Internal order and lexicographic minimum across legal records.
        legal = enumerate_legal_records(case)
        pair_keys = [tuple(int(r[f]) for f in case.fields) for r in pair]
        self.assertLess(pair_keys[0], pair_keys[1])
        # The independent exhaustive oracle is the authority on the
        # lexicographically smallest indistinguishable conflicting pair.
        oracle = exhaustive_audit(case)
        oracle_ops = next(r for r in oracle["receivers"] if r["name"] == "ops")
        self.assertEqual(
            ops["leaks"],
            oracle_ops["leaks"],
        )
        # And the witness records really are legal.
        from veilresponse.expr import evaluate
        for record in pair:
            self.assertTrue(evaluate(case.legal, record))

    def test_compliant_full_visibility(self):
        case = load_case(SAMPLES / "compliant.json")
        result = run_audit(case)
        self.assertEqual(result["status"], "compliant")
        self.assertTrue(all(r["compliant"] for r in result["receivers"]))

    def test_empty_legal_set_vacuously_compliant(self):
        case = load_case(SAMPLES / "empty_legal.json")
        result = run_audit(case)
        self.assertFalse(result["legal_records_feasible"])
        self.assertEqual(result["status"], "compliant")
        self.assertTrue(all(r["compliant"] for r in result["receivers"]))
        # The rule itself cannot have a feasible assignment either.
        self.assertFalse(result["rule_diagnostics"][0]["has_feasible_assignment"])

    def test_infeasible_and_shadowed_rule_diagnostics(self):
        case = load_case(SAMPLES / "infeasible_rules.json")
        result = run_audit(case)
        diag = result["rule_diagnostics"]
        self.assertFalse(diag[0]["has_feasible_assignment"])
        self.assertFalse(diag[1]["has_feasible_assignment"])
        self.assertTrue(diag[2]["can_fire"])

    def test_default_branch_leak(self):
        case = load_case(SAMPLES / "default_branch.json")
        result = run_audit(case)
        blind = next(r for r in result["receivers"] if r["name"] == "sees-nothing")
        seeing = next(r for r in result["receivers"] if r["name"] == "sees-t")
        self.assertFalse(blind["compliant"])
        codes = {tuple(leak["codes"]) for leak in blind["leaks"]}
        self.assertIn((10, 20), codes)
        self.assertTrue(seeing["compliant"])

    def test_audit_output_is_json_serializable(self):
        for path in SAMPLES.glob("*.json"):
            with self.subTest(path=path.name):
                result = run_audit(load_case(path))
                json.dumps(result)


if __name__ == "__main__":
    unittest.main()
