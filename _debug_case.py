import json
import sys

sys.path.insert(0, ".")
from veilresponse.model import parse_case
from veilresponse.audit import run_audit
from veilresponse.exhaustive import exhaustive_audit

raw = {
    "fields": ["f0", "f1", "f2", "f3"],
    "derived_facts": {"d0": "f2"},
    "legal": {"not": {"iff": [{"iff": ["f0", "f0"]}, {"not": "f1"}]}},
    "rules": [
        {"when": "d0", "code": 100},
        {"when": "f0", "code": 200},
        {"when": {"xor": [{"or": [{"or": ["f1", "d0"]}, {"imp": ["d0", "f0"]}]},
                            {"xor": ["f2", "f2"]}]}, "code": 200},
        {"when": "d0", "code": 100},
    ],
    "default_code": 404,
    "receivers": [
        {"name": "rcv0", "visible_fields": [], "derived_facts": ["d0"]},
        {"name": "rcv1", "visible_fields": [], "derived_facts": []},
        {"name": "rcv2", "visible_fields": [], "derived_facts": []},
    ],
    "repair": {"merge_costs": {"100": 2, "200": 2, "404": 5},
               "default_code_optional": True},
}
case = parse_case(raw)
sa = run_audit(case)
ea = exhaustive_audit(case)
for g, o in zip(sa["receivers"], ea["receivers"]):
    if g["leaks"] != o["leaks"]:
        print("RECEIVER", g["name"])
        print("SAT   ", json.dumps(g["leaks"]))
        print("ORACLE", json.dumps(o["leaks"]))
