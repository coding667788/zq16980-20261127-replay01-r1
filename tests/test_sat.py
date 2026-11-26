import itertools
import itertools
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veilresponse.sat import SATSolver
from veilresponse.tseitin import Encoder
from veilresponse.expr import Builder, evaluate


class SATSolverTests(unittest.TestCase):
    def test_unit_conflict(self):
        sat = SATSolver()
        sat.add_clause([1])
        sat.add_clause([-1])
        self.assertIsNone(sat.solve())

    def test_repeated_queries_reset_state(self):
        sat = SATSolver()
        sat.add_clause([1, 2])
        self.assertIsNotNone(sat.solve([-1]))
        self.assertIsNotNone(sat.solve([-2]))
        self.assertIsNone(sat.solve([-1, -2]))
        # Formula itself remains satisfiable after the UNSAT query.
        self.assertIsNotNone(sat.solve())

    def test_tautology_is_dropped(self):
        sat = SATSolver()
        sat.add_clause([1, -1])
        self.assertIsNotNone(sat.solve())

    def test_pigeonhole_unsat(self):
        # 3 pigeons into 2 holes: classic small UNSAT.
        sat = SATSolver()
        pigeon = [[sat.new_var() for _ in range(2)] for _ in range(3)]
        for row in pigeon:
            sat.add_clause(row)
        for hole in range(2):
            for p in range(3):
                for q in range(p + 1, 3):
                    sat.add_clause([-pigeon[p][hole], -pigeon[q][hole]])
        self.assertIsNone(sat.solve())

    def test_gates_match_boolean_truth_tables(self):
        rng = random.Random(7)
        for _ in range(40):
            enc = Encoder(SATSolver())
            a = enc.sat.new_var()
            b = enc.sat.new_var()
            op = rng.choice(["and", "or", "xor", "iff"])
            if op == "and":
                z, fn = enc.gate_and([a, b]), lambda x, y: x and y
            elif op == "or":
                z, fn = enc.gate_or([a, b]), lambda x, y: x or y
            elif op == "xor":
                z, fn = enc.gate_xor(a, b), lambda x, y: x != y
            else:
                z, fn = enc.gate_iff(a, b), lambda x, y: x == y
            for va, vb in (
                (False, False), (False, True), (True, False), (True, True)
            ):
                expected = fn(va, vb)
                assumptions = [a if va else -a, b if vb else -b,
                               z if fn(va, vb) else -z]
                self.assertIsNotNone(
                    enc.sat.solve(assumptions),
                    f"{op} gate wrong for {va},{vb}",
                )
                bad = [a if va else -a, b if vb else -b,
                       z if not fn(va, vb) else -z]
                self.assertIsNone(
                    enc.sat.solve(bad),
                    f"{op} gate unexpectedly satisfiable for {va},{vb}",
                )


class TseitinEquivalenceTests(unittest.TestCase):
    def test_random_expressions_match_tree_evaluator(self):
        rng = random.Random(23)
        builder = Builder()
        names = ["a", "b", "c", "d"]
        for _ in range(30):
            from veilresponse.fuzzgen import random_expr

            expr_json = random_expr(rng, names, 3)
            node = builder.parse(expr_json)
            enc = Encoder(SATSolver())
            lits = {name: enc.named_literal(f"x::{name}") for name in names}
            target = enc.encode(node, "x")
            for bits in itertools.product((False, True), repeat=len(names)):
                assignment = dict(zip(names, bits))
                expected = evaluate(node, assignment)
                assumptions = [
                    lits[name] if value else -lits[name]
                    for name, value in assignment.items()
                ]
                assumptions.append(target if expected else -target)
                self.assertIsNotNone(enc.sat.solve(assumptions))
                assumptions[-1] = -target if expected else target
                self.assertIsNone(enc.sat.solve(assumptions))

    def test_strict_lex_order(self):
        enc = Encoder(SATSolver())
        xs = [enc.sat.new_var() for _ in range(3)]
        ys = [enc.sat.new_var() for _ in range(3)]
        enc.assert_strict_lex_order(xs, ys)
        count = 0
        for bits in itertools.product((False, True), repeat=6):
            xv, yv = bits[:3], bits[3:]
            assumptions = [
                (xs[i] if xv[i] else -xs[i]) for i in range(3)
            ] + [
                (ys[i] if yv[i] else -ys[i]) for i in range(3)
            ]
            satisfiable = enc.sat.solve(assumptions) is not None
            self.assertEqual(satisfiable, xv < yv)
            count += satisfiable
        # Number of strictly ordered 3-bit pairs: (2^3 * (2^3 - 1)) / 2.
        self.assertEqual(count, 28)


if __name__ == "__main__":
    unittest.main()
