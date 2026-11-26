"""JSON command-line entry points: ``python -m veilresponse audit|repair CASE``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .audit import run_audit
from .model import load_case
from .repair import plan_repair


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veilresponse",
        description="Audit indirect boolean-flag leakage and plan code merges.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="audit a CASE file")
    audit.add_argument("case", help="path to the synthetic JSON case")

    repair = sub.add_parser("repair", help="plan a minimum-cost repair")
    repair.add_argument("case", help="path to the synthetic JSON case")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        case = load_case(args.case)
        result = run_audit(case) if args.command == "audit" else plan_repair(case)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
