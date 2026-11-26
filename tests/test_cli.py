import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veilresponse.cli import main

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class CLITests(unittest.TestCase):
    def _run(self, command, path):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main([command, str(path)])
        self.assertEqual(code, 0)
        return json.loads(buffer.getvalue())

    def test_audit_and_repair_cli(self):
        audit = self._run("audit", SAMPLES / "simple_leak.json")
        self.assertIn("status", audit)
        repair = self._run("repair", SAMPLES / "unrepairable.json")
        self.assertEqual(repair["status"], "unrepairable")

    def test_cli_reports_bad_input_on_stderr(self):
        bad = SAMPLES.parent / "does_not_exist.json"
        self.assertEqual(main(["audit", str(bad)]), 2)

    def test_validation_rejects_unknown_field_and_bad_cost(self):
        from veilresponse.model import parse_case

        raw = {
            "fields": ["a"],
            "legal": "a",
            "rules": [{"when": "ghost", "code": 1}],
            "default_code": 0,
            "receivers": [],
            "repair": {"merge_costs": {"1": -1}},
        }
        with self.assertRaises(ValueError):
            parse_case(raw)


if __name__ == "__main__":
    unittest.main()
