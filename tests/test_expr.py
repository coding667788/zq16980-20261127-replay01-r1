import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veilresponse.expr import Builder, evaluate


class ExprTests(unittest.TestCase):
    def setUp(self):
        self.builder = Builder()

    def test_parse_and_evaluate_operators(self):
        b = self.builder
        tree = b.parse({
            "and": [
                "a",
                {"or": [False, {"not": "b"}]},
                {"xor": ["a", "b"]},
                {"iff": ["a", {"imp": ["b", "a"]}]},
            ]
        })
        # Pick an assignment where the whole expression holds:
        assignment = {"a": True, "b": False}
        self.assertTrue(evaluate(tree, assignment))
        assignment = {"a": False, "b": False}
        self.assertFalse(evaluate(tree, assignment))

    def test_constant_folding(self):
        b = self.builder
        self.assertIs(b.parse({"and": [True, "a"]}), b.variable("a"))
        self.assertIs(b.parse({"or": [False, "a"]}), b.variable("a"))
        self.assertEqual(b.parse({"not": True}), b.false)
        self.assertEqual(b.parse({"and": []}), b.true)
        self.assertEqual(b.parse({"or": []}), b.false)

    def test_shared_subexpression_is_same_node(self):
        b = self.builder
        first = b.parse({"and": ["a", {"or": ["b", "c"]}]})
        second = b.parse({"and": ["a", {"or": ["b", "c"]}]})
        self.assertIs(first, second)
        # Double negation collapses.
        self.assertIs(b.parse({"not": {"not": "a"}}), b.variable("a"))

    def test_rejects_bad_expressions(self):
        b = self.builder
        with self.assertRaises(ValueError):
            b.parse({"xor": ["a"]})
        with self.assertRaises(ValueError):
            b.parse({"bogus": ["a"]})
        with self.assertRaises(ValueError):
            b.parse(123)

    def test_unbound_variable_raises(self):
        node = self.builder.variable("a")
        with self.assertRaises(ValueError):
            evaluate(node, {})


if __name__ == "__main__":
    unittest.main()
