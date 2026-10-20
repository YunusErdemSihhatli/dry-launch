import unittest

import helpers
import pricing

KEYS = panel_keys = ("price_too_cheap", "price_bargain", "price_expensive", "price_too_expensive")


def row(a, b, c, d):
    return {KEYS[0]: a, KEYS[1]: b, KEYS[2]: c, KEYS[3]: d}


class PricingTests(unittest.TestCase):
    def test_drops_out_of_order_and_non_numeric(self):
        rows = [row(5, 10, 20, 30), row(50, 10, 20, 30), row("x", 1, 2, 3), row(0, 1, 2, 3)]
        tuples, dropped = pricing.usable(rows, KEYS)
        self.assertEqual(len(tuples), 1)
        self.assertEqual(dropped, 3)

    def test_too_few_answers_gives_no_range(self):
        result, _ = pricing.from_answers([row(5, 10, 20, 30)] * 3, KEYS)
        self.assertIsNone(result)

    def test_identical_answers_give_expected_points(self):
        result, _ = pricing.from_answers([row(10, 15, 20, 25)] * 10, KEYS)
        p = result["points"]
        self.assertAlmostEqual(p["PMC"], 10, delta=0.5)
        self.assertAlmostEqual(p["PME"], 20, delta=0.5)
        self.assertLessEqual(p["PMC"], p["PME"])

    def test_spread_answers_stay_inside_the_data(self):
        rows = [row(5 + i % 5, 10 + i % 5, 20 + i % 5, 30 + i % 5) for i in range(20)]
        result, _ = pricing.from_answers(rows, KEYS)
        lo, hi = result["range"]
        self.assertTrue(5 <= lo < hi <= 34)

    def test_report_lines_mention_range(self):
        result, _ = pricing.from_answers([row(10, 15, 20, 25)] * 10, KEYS)
        text = "\n".join(pricing.report_lines(result, 0, "TL"))
        self.assertIn("Acceptable range", text)
        self.assertIn("TL", text)


if __name__ == "__main__":
    unittest.main()
