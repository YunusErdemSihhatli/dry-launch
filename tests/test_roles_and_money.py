import io
import json
import os
import shutil
import unittest
from contextlib import redirect_stdout

from helpers import make_project, price_text, r1_answer, read_json, read_text, write_json

import panel
import tally


def cards_of(d):
    return panel.load_cards(d)[0]


class PriceUnderstandingTests(unittest.TestCase):
    """The price and income check applies to every buyer, whatever it answered to buys."""

    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 10, 7, False)
        self.features = panel.load_inputs(self.d)[2]
        self.price = panel.price_of(panel.load_inputs(self.d)[0])
        self.buyer = next(c for c in cards_of(self.d) if c["decision_type"] == "buyer")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def answer(self, buys, understood, income_text=None):
        a = r1_answer(self.buyer["id"], self.features, "buyer", buys=buys, price=self.price, income=self.buyer["income"])
        a["price_as_i_understand_it"] = understood
        if income_text is not None:
            a["my_income"] = income_text
        return a

    def test_refusal_with_no_price_statement_is_refused(self):
        a = self.answer(False, "nothing, too expensive")
        self.assertIn("has no amount", panel.answer_problem(a, self.buyer, self.features, "1", self.price))

    def test_refusal_with_a_wrong_price_statement_is_refused(self):
        a = self.answer(False, "90 USD per month")
        self.assertIn("does not match the price", panel.answer_problem(a, self.buyer, self.features, "1", self.price))

    def test_yes_with_no_price_statement_is_refused(self):
        a = self.answer(True, "nothing, too expensive")
        self.assertIn("has no amount", panel.answer_problem(a, self.buyer, self.features, "1", self.price))

    def test_correct_refusal_is_accepted(self):
        a = self.answer(False, "39 USD as a one-time payment")
        self.assertIsNone(panel.answer_problem(a, self.buyer, self.features, "1", self.price))

    def test_misunderstood_answers_skip_the_check(self):
        a = self.answer(False, "nothing, too expensive")
        a["misunderstood"] = True
        self.assertIsNone(panel.answer_problem(a, self.buyer, self.features, "1", self.price))


class MisreadTests(unittest.TestCase):
    """First misread: dispatch again. Second misread: keep the answer, flag it misunderstood."""

    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 10, 7, False)
        self.features = panel.load_inputs(self.d)[2]
        self.price = panel.price_of(panel.load_inputs(self.d)[0])
        self.buyer = next(c for c in cards_of(self.d) if c["decision_type"] == "buyer")
        self.path = panel.answer_path(self.d, "1", self.buyer["id"])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_answer(self, understood):
        a = r1_answer(self.buyer["id"], self.features, "buyer", buys=False, price=self.price,
                      income=self.buyer["income"])
        a["price_as_i_understand_it"] = understood
        write_json(self.path, a)

    def test_first_misread_asks_for_another_try(self):
        self.write_answer("nothing, too expensive")
        r = panel.review_round1(self.d, self.buyer, self.features, self.price)
        self.assertTrue(r.startswith("misread"), r)
        self.assertNotIn("misunderstood", read_json(self.path))

    def test_checking_the_same_file_twice_is_one_attempt(self):
        self.write_answer("nothing, too expensive")
        panel.review_round1(self.d, self.buyer, self.features, self.price)
        r = panel.review_round1(self.d, self.buyer, self.features, self.price)
        self.assertTrue(r.startswith("misread"), r)
        self.assertEqual(panel._load_attempts(self.d)[self.buyer["id"]]["count"], 1)

    def test_second_misread_is_kept_and_flagged(self):
        self.write_answer("nothing, too expensive")
        panel.review_round1(self.d, self.buyer, self.features, self.price)
        self.write_answer("nothing, too expensive, really no")  # a new attempt, still wrong
        self.assertEqual(panel.review_round1(self.d, self.buyer, self.features, self.price), "misunderstood")
        flagged = read_json(self.path)
        self.assertTrue(flagged["misunderstood"])
        self.assertIsNone(panel.answer_problem_file(self.path, self.buyer, self.features, "1", self.price))

    def test_correct_answer_is_valid_on_first_try(self):
        self.write_answer("39 USD as a one-time payment")
        self.assertIsNone(panel.review_round1(self.d, self.buyer, self.features, self.price))

    def test_check_command_reports_misunderstood(self):
        self.write_answer("nothing, too expensive")
        panel.review_round1(self.d, self.buyer, self.features, self.price)
        self.write_answer("nothing, too expensive, really no")
        out = io.StringIO()
        with redirect_stdout(out):
            panel.cmd_check(self.d, "1")
        self.assertIn("misread the price or their income twice", out.getvalue())

    def test_save_refuses_first_misread(self):
        bad = r1_answer(self.buyer["id"], self.features, "buyer", buys=False, price=self.price, income=self.buyer["income"])
        bad["price_as_i_understand_it"] = "nothing, too expensive"
        with self.assertRaisesRegex(panel.PanelError, "misread"):
            panel.cmd_save(self.d, "1", self.buyer["id"], json.dumps(bad))


class MoneyParsingTests(unittest.TestCase):
    def test_k_suffix(self):
        self.assertEqual(panel.parse_money("269k"), (269000.0, None))
        self.assertEqual(panel.parse_money("269K per month"), (269000.0, "month"))
        self.assertEqual(panel.parse_money("269 k a month"), (269000.0, "month"))

    def test_bin_suffix(self):
        self.assertEqual(panel.parse_money("269 bin TL aylık"), (269000.0, "month"))
        self.assertEqual(panel.parse_money("269 thousand USD"), (269000.0, None))

    def test_m_suffix(self):
        self.assertEqual(panel.parse_money("1.2M USD per year"), (1200000.0, "year"))
        self.assertEqual(panel.parse_money("2,5 milyon TL"), (2500000.0, None))
        self.assertEqual(panel.parse_money("1.2m"), (1200000.0, None))

    def test_plain_numbers_unchanged(self):
        self.assertEqual(panel.parse_money("1,200 USD per month"), (1200.0, "month"))
        self.assertEqual(panel.parse_money("1.200 TRY a month"), (1200.0, "month"))


class UserIncomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 10, 7, False)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_user_gets_a_qualitative_income_sentence_by_band(self):
        cards = cards_of(self.d)
        user = next(c for c in cards if c["decision_type"] == "user")
        user["income_band"] = "low"
        self.assertEqual(panel.income_phrase(user, panel.load_inputs(self.d)[0]), "Your family is careful with money.")
        user["income_band"] = "middle"
        self.assertEqual(panel.income_phrase(user, panel.load_inputs(self.d)[0]), "Your family can afford some extras.")
        user["income_band"] = "high"
        self.assertEqual(panel.income_phrase(user, panel.load_inputs(self.d)[0]), "Your family rarely worries about money.")

    def test_comprehension_fields_only_for_buyers(self):
        customer = panel.load_inputs(self.d)[0]
        for dtype in ("user", "influencer"):
            s = panel.schema_text("P01", dtype, "1", panel.load_inputs(self.d)[2], panel.price_of(customer))
            self.assertNotIn("price_as_i_understand_it", s)
            self.assertNotIn('"my_income"', s)


class NamesTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_example_names_are_used(self):
        panel.cmd_init(self.d, 10, 7, True)
        names = read_json(os.path.join(self.d, "customer.json"))["names"]
        self.assertIn(cards_of(self.d)[0]["name"].split(" ")[0], names)

    def test_missing_names_list_prints_a_note(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        del c["names"]
        write_json(p, c)
        out = io.StringIO()
        with redirect_stdout(out):
            panel.cmd_init(self.d, 10, 7, False)
        self.assertIn("has no 'names' list", out.getvalue())


class RoleListTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 100, 7, False)
        self.customer = panel.load_inputs(self.d)[0]
        self.roles = {r["decision_type"]: r for r in self.customer["roles"]}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_child_gets_child_objections_and_habits_only(self):
        child = self.roles["user"]
        users = [c for c in cards_of(self.d) if c["decision_type"] == "user"]
        self.assertTrue(users)
        for u in users:
            self.assertIn(u["objection"], child["objections"])
            self.assertIn(u["habit"], child["habits"])
            self.assertIn(u["temper"], child["tempers"])

    def test_role_without_lists_falls_back_to_global(self):
        buyers = [c for c in cards_of(self.d) if c["decision_type"] == "buyer"]
        self.assertTrue(all(b["objection"] in self.customer["objections"] for b in buyers))
        self.assertTrue(all(b["habit"] in self.customer["habits"] for b in buyers))

    def test_empty_role_list_is_refused(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["roles"][1]["objections"] = []
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "'objections' must be a non-empty list"):
            panel.load_inputs(self.d)

    def test_current_spend_uses_market_currency(self):
        buyer = next(c for c in cards_of(self.d) if c["decision_type"] == "buyer")
        self.assertIn("USD a month", buyer["current_spend"])
        self.assertNotIn("{currency}", buyer["current_spend"])


class FeatureForTests(unittest.TestCase):
    def setUp(self):
        self.features = [{"id": "F1", "name": "a", "what": "b", "steps": ["s"]},
                         {"id": "F2", "name": "c", "what": "d", "steps": ["s"], "for": ["buyer"]}]

    def row(self, pid, dtype, v1, v2):
        return {"id": pid, "decision_type": dtype,
                "feature_reactions": [
                    {"feature": "F1", "understood": True, "value": v1, "complexity": 2, "comment": "x", "missing": ""},
                    {"feature": "F2", "understood": True, "value": v2, "complexity": 2, "comment": "x", "missing": ""}]}

    def test_for_limits_scoring_to_its_roles(self):
        rows = [self.row("P01", "buyer", 4, 5), self.row("P02", "buyer", 4, 5),
                self.row("P03", "user", 4, 1), self.row("P04", "user", 4, 1)]
        stats = {s["feature"]["id"]: s for s in tally.feature_stats(self.features, rows)}
        self.assertEqual(stats["F2"]["avg_value"], 5.0)
        self.assertEqual(stats["F2"]["scored_for"], ["buyer"])
        self.assertEqual(stats["F2"]["per_role"]["user"], 1.0)
        self.assertEqual(stats["F1"]["avg_value"], 4.0)
        self.assertEqual(stats["F1"]["scored_for"], ["buyer", "user", "influencer"])

    def test_feature_without_buyers_is_not_scored(self):
        rows = [self.row("P03", "user", 4, 1)]
        stats = {s["feature"]["id"]: s for s in tally.feature_stats(self.features, rows)}
        self.assertTrue(stats["F2"]["recommendation"].startswith("n/a"))

    def test_report_shows_scored_from_and_role_table(self):
        tmp, d = make_project()
        try:
            panel.cmd_init(d, 10, 7, False)
            features = panel.load_inputs(d)[2]
            price = panel.price_of(panel.load_inputs(d)[0])
            for c in cards_of(d):
                write_json(panel.answer_path(d, "1", c["id"]),
                           r1_answer(c["id"], features, c["decision_type"], price=price if c["decision_type"] == "buyer" else None,
                                     income=c["income"]))
            tally.cmd_results(d)
            text = read_text(os.path.join(d, "report.md"))
            self.assertIn("| feature | scored from |", text)
            self.assertIn("### Feature value by role", text)
            self.assertIn("F2 Parent progress view | buyer", text)
        finally:
            shutil.rmtree(tmp)


class FeatureForValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_invalid_for_is_refused(self):
        p = os.path.join(self.d, "features.json")
        f = read_json(p)
        f["features"][1]["for"] = ["manager"]
        write_json(p, f)
        with self.assertRaisesRegex(panel.PanelError, "'for' must be"):
            panel.load_inputs(self.d)


if __name__ == "__main__":
    unittest.main()
