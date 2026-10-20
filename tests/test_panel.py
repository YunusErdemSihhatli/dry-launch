import io
import json
import os
import re
import shutil
import unittest
from contextlib import redirect_stdout

from helpers import make_project, price_text, r1_answer, r2_answer, read_json, read_text, task_answer, write_json

import panel

FEATURES = [{"id": "F1", "name": "a", "what": "b", "steps": ["s1", "s2"]},
            {"id": "F2", "name": "c", "what": "d", "steps": ["s1"]}]


def cards_of(d):
    return panel.load_cards(d)[0]


def price_of_project(d):
    return panel.price_of(panel.load_inputs(d)[0])


class DealTests(unittest.TestCase):
    def test_quota_is_exact_and_fair(self):
        self.assertEqual(panel.quota([{"share": 0.6}, {"share": 0.4}], 5), [3, 2])
        for n in range(1, 40):
            self.assertEqual(sum(panel.quota([{"share": 0.3}, {"share": 0.3}, {"share": 0.4}], n)), n)

    def test_same_seed_same_cards_different_seed_differs(self):
        tmp, d = make_project()
        try:
            panel.cmd_init(d, 20, 7, False)
            first = cards_of(d)
            panel.cmd_init(d, 20, 7, True)
            self.assertEqual(first, cards_of(d))
            panel.cmd_init(d, 20, 8, True)
            self.assertNotEqual(first, cards_of(d))
        finally:
            shutil.rmtree(tmp)

    def test_init_deals_roles_with_decision_types(self):
        tmp, d = make_project()
        try:
            panel.cmd_init(d, 10, 7, False)
            types = [c["decision_type"] for c in cards_of(d)]
            self.assertEqual((types.count("buyer"), types.count("user"), types.count("influencer")), (4, 4, 2))
            self.assertTrue(os.path.exists(os.path.join(d, "personas", "P01.md")))
        finally:
            shutil.rmtree(tmp)


class MarketAndBandTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_incomes_fall_inside_their_band(self):
        panel.cmd_init(self.d, 100, 7, False)
        bounds = {"low": (1200, 4300), "middle": (4300, 11400), "high": (11400, 25000)}
        for c in cards_of(self.d):
            lo, hi = bounds[c["income_band"]]
            self.assertTrue(lo <= c["income"] <= hi, (c["id"], c["income"], c["income_band"]))

    def test_band_shares_are_respected(self):
        panel.cmd_init(self.d, 100, 7, False)
        cards = cards_of(self.d)
        counts = {b: sum(1 for c in cards if c["income_band"] == b) for b in ("low", "middle", "high")}
        self.assertEqual(counts, {"low": 40, "middle": 40, "high": 20})

    def test_role_band_shares_override_the_market(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["roles"][0]["band_shares"] = {"low": 0, "middle": 0, "high": 1}
        write_json(p, c)
        panel.cmd_init(self.d, 100, 7, False)
        buyers = [x for x in cards_of(self.d) if x["decision_type"] == "buyer"]
        self.assertTrue(buyers and all(x["income_band"] == "high" for x in buyers))

    def test_band_shares_must_cover_every_band(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["roles"][0]["band_shares"] = {"low": 1}
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "non-negative share for every income band"):
            panel.load_inputs(self.d)

    def test_init_refuses_unconfirmed_market(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["market"]["confirmed"] = False
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "not confirmed"):
            panel.cmd_init(self.d, 10, 7, False)

    def test_market_needs_year_and_bool_confirmed(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["market"]["income_year"] = "2024"
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "income_year"):
            panel.load_inputs(self.d)

    def test_affordability_table_lists_bands_and_price_share(self):
        out = io.StringIO()
        with redirect_stdout(out):
            panel.cmd_affordability(self.d)
        text = out.getvalue()
        for band in ("| low |", "| middle |", "| high |"):
            self.assertIn(band, text)
        self.assertIn("confirmed: yes", text)

    def test_affordability_needs_a_price(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        del c["price"]
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "needs a 'price'"):
            panel.cmd_affordability(self.d)

    def test_health_warning_when_price_is_too_high_for_most_buyers(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["price"] = {"amount": 9000, "period": "month"}
        write_json(p, c)
        out = io.StringIO()
        with redirect_stdout(out):
            panel.cmd_init(self.d, 100, 7, False)
        self.assertIn("Warning: the price is more than 15% of the monthly income", out.getvalue())

    def test_no_health_warning_for_a_cheap_price(self):
        out = io.StringIO()
        with redirect_stdout(out):
            panel.cmd_init(self.d, 100, 7, False)
        self.assertNotIn("Warning", out.getvalue())


class PriceTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_price_needs_a_period(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["price"] = {"amount": 39}
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "period' is required"):
            panel.load_inputs(self.d)

    def test_price_must_be_an_object_not_a_number(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["price"] = 39
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "must be an object"):
            panel.load_inputs(self.d)

    def test_no_price_means_no_price_questions(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        del c["price"]
        write_json(p, c)
        panel.cmd_init(self.d, 10, 7, False)
        panel.cmd_briefs(self.d, "1", 10)
        buyer = next(x for x in cards_of(self.d) if x["decision_type"] == "buyer")
        text = read_text(os.path.join(self.d, "briefs", "r1", buyer["id"] + ".md"))
        self.assertNotIn("price_too_cheap", text)
        self.assertNotIn("i_pay", text)

    def test_yearly_price_is_spread_over_12_months_in_the_share(self):
        price = {"amount": 120, "period": "year", "_currency": "USD"}
        self.assertEqual(panel.monthly_price(price), 10)
        self.assertAlmostEqual(panel.price_share(price, 1000), 1.0)

    def test_brief_states_price_share_for_buyers(self):
        panel.cmd_init(self.d, 10, 7, False)
        panel.cmd_briefs(self.d, "1", 10)
        buyer = next(x for x in cards_of(self.d) if x["decision_type"] == "buyer")
        text = read_text(os.path.join(self.d, "briefs", "r1", buyer["id"] + ".md"))
        share = 100.0 * 39 / buyer["income"]
        self.assertIn("This is %.1f%% of your household's monthly income." % share, text)
        self.assertIn("39 USD as a one-time payment", text)

    def test_user_brief_has_no_price_line(self):
        panel.cmd_init(self.d, 10, 7, False)
        panel.cmd_briefs(self.d, "1", 10)
        user = next(x for x in cards_of(self.d) if x["decision_type"] == "user")
        self.assertNotIn("monthly income.", read_text(os.path.join(self.d, "briefs", "r1", user["id"] + ".md")))

    def test_brief_shows_current_spend_when_given(self):
        panel.cmd_init(self.d, 10, 7, False)
        panel.cmd_briefs(self.d, "1", 10)
        buyer = next(x for x in cards_of(self.d) if x["decision_type"] == "buyer")
        self.assertIn("Right now you already spend on this kind of thing: pays for one children's learning app",
                      read_text(os.path.join(self.d, "briefs", "r1", buyer["id"] + ".md")))


class ComprehensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 10, 7, False)
        self.features = panel.load_inputs(self.d)[2]
        self.price = price_of_project(self.d)
        self.buyer = next(x for x in cards_of(self.d) if x["decision_type"] == "buyer")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def answer(self, **over):
        a = r1_answer(self.buyer["id"], self.features, "buyer", price=self.price, income=self.buyer["income"])
        a.update(over)
        return a

    def problem(self, a, rnd="1"):
        return panel.answer_problem(a, self.buyer, self.features, rnd, self.price if rnd == "1" else None)

    def test_matching_statements_pass(self):
        self.assertIsNone(self.problem(self.answer()))

    def test_wrong_amount_fails(self):
        self.assertIn("does not match the price", self.problem(self.answer(i_pay="90 USD as a one-time payment")))

    def test_wrong_period_fails(self):
        self.assertIn("period", self.problem(self.answer(i_pay="39 USD per month")))

    def test_missing_period_fails(self):
        self.assertIn("no period", self.problem(self.answer(i_pay="39 USD")))

    def test_income_outside_ten_percent_fails(self):
        wrong = int(self.buyer["income"] * 1.5)
        self.assertIn("does not match your household income",
                      self.problem(self.answer(my_income="%d USD a month" % wrong)))

    def test_income_within_ten_percent_passes(self):
        near = int(self.buyer["income"] * 1.05)
        self.assertIsNone(self.problem(self.answer(my_income="%d USD a month" % near)))

    def test_yearly_income_statement_is_converted(self):
        yearly = self.buyer["income"] * 12
        self.assertIsNone(self.problem(self.answer(my_income="%d USD per year" % yearly)))

    def test_r2_buyer_needs_no_comprehension_fields(self):
        a = r2_answer(self.buyer["id"], self.features, "buyer")
        self.assertIsNone(panel.answer_problem(a, self.buyer, self.features, "2", None))

    def test_user_needs_no_comprehension_fields(self):
        user = next(x for x in cards_of(self.d) if x["decision_type"] == "user")
        a = r1_answer(user["id"], self.features, "user")
        self.assertIsNone(panel.answer_problem(a, user, self.features, "1", None))

    def test_schema_lists_comprehension_fields_for_priced_buyers_only(self):
        s = panel.schema_text(self.buyer["id"], "buyer", "1", self.features, self.price)
        self.assertIn('"i_pay"', s)
        self.assertIn('"my_income"', s)
        self.assertNotIn('"i_pay"', panel.schema_text("P09", "user", "1", self.features, None))

    def test_parse_money_formats(self):
        self.assertEqual(panel.parse_money("1,200 USD per month"), (1200.0, "month"))
        self.assertEqual(panel.parse_money("1.200 TRY a month"), (1200.0, "month"))
        self.assertEqual(panel.parse_money("1,200.50 USD per year"), (1200.5, "year"))
        self.assertEqual(panel.parse_money("1.200,50 TL aylık"), (1200.5, "month"))
        self.assertEqual(panel.parse_money("39 USD one-time"), (39.0, "once"))
        self.assertEqual(panel.parse_money("no idea"), (None, None))


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 10, 7, False)
        self.cards = cards_of(self.d)
        self.by_type = {}
        for c in self.cards:
            self.by_type.setdefault(c["decision_type"], c)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def brief(self, rnd, pid):
        return read_text(os.path.join(self.d, "briefs", "r" + rnd, pid + ".md"))

    def test_buyer_brief_has_price_questions_user_does_not(self):
        panel.cmd_briefs(self.d, "1", 10)
        self.assertIn("price_too_cheap", self.brief("1", self.by_type["buyer"]["id"]))
        self.assertNotIn("price_too_cheap", self.brief("1", self.by_type["user"]["id"]))

    def test_schema_matches_role(self):
        panel.cmd_briefs(self.d, "1", 10)
        self.assertIn('"wants_it"', self.brief("1", self.by_type["user"]["id"]))
        self.assertIn('"would_recommend"', self.brief("1", self.by_type["influencer"]["id"]))
        self.assertNotIn('"buys"', self.brief("1", self.by_type["influencer"]["id"]))
        self.assertIn('"buys"', self.brief("1", self.by_type["buyer"]["id"]))

    def test_income_line_has_currency_and_monthly_net(self):
        panel.cmd_briefs(self.d, "1", 10)
        c = self.by_type["user"]
        self.assertRegex(self.brief("1", c["id"]), r"monthly net income is about [\d,]+ USD")

    def test_thinking_line_depends_on_role(self):
        panel.cmd_briefs(self.d, "1", 10)
        self.assertIn("your own money", self.brief("1", self.by_type["buyer"]["id"]))
        self.assertNotIn("your own money", self.brief("1", self.by_type["user"]["id"]))
        self.assertIn("whether you would actually play with it", self.brief("1", self.by_type["user"]["id"]))

    def test_tone_is_neutral(self):
        panel.cmd_briefs(self.d, "1", 10)
        text = self.brief("1", self.by_type["buyer"]["id"])
        self.assertIn("Both yes and no are useful answers", text)
        self.assertNotIn("Politeness", text)

    def test_brief_only_names_its_own_persona(self):
        panel.cmd_briefs(self.d, "1", 10)
        self.assertEqual(set(re.findall(r"\bP\d\d\b", self.brief("1", "P03"))), {"P03"})

    def test_one_reaction_entry_per_feature(self):
        panel.cmd_briefs(self.d, "1", 10)
        text = self.brief("1", "P02")
        self.assertEqual(len(re.findall(r'"feature": "F1"', text)), 1)
        self.assertEqual(len(re.findall(r'"feature": "F2"', text)), 1)

    def test_task_round_refuses_without_screens(self):
        for f in panel.screens_list(self.d):
            os.remove(f)
        with self.assertRaisesRegex(panel.PanelError, "needs screenshots"):
            panel.cmd_briefs(self.d, "task", 10)

    def test_task_brief_lists_checkpoints_in_order(self):
        panel.cmd_briefs(self.d, "task", 10)
        text = read_text(os.path.join(self.d, "briefs", "task", "P01.md"))
        self.assertIn("Checkpoints, in order", text)
        self.assertIn("1) Open the coding board", text)

    def test_r2_needs_answered_questions(self):
        with self.assertRaisesRegex(panel.PanelError, "no answered questions"):
            panel.cmd_briefs(self.d, "2", 10)

    def test_r2_brief_contains_team_answer_and_own_round1(self):
        features = self.features()
        price = price_of_project(self.d)
        for c in self.cards:
            write_json(panel.answer_path(self.d, "1", c["id"]),
                       r1_answer(c["id"], features, c["decision_type"], price=price if c["decision_type"] == "buyer" else None,
                                 income=c["income"]))
        write_json(os.path.join(self.d, "qa", "questions.json"), [{"id": "Q1", "text": "How long does the battery last?"}])
        with open(os.path.join(self.d, "qa", "answers.md"), "w", encoding="utf-8") as fh:
            fh.write("### Q1\n\nSix hours on one charge.\n")
        panel.cmd_briefs(self.d, "2", 10)
        text = self.brief("2", "P02")
        self.assertIn("Six hours on one charge.", text)
        self.assertIn('"id": "P02"', text)

    def features(self):
        return panel.load_inputs(self.d)[2]


class AnswerValidationTests(unittest.TestCase):
    def ok(self, a, dtype="buyer", rnd="1", price=None):
        card = {"id": "P01", "decision_type": dtype, "income": 5000}
        return panel.answer_problem(a, card, FEATURES, rnd, price)

    def test_valid_user_answer_passes(self):
        self.assertIsNone(self.ok(r1_answer("P01", FEATURES, "user"), dtype="user"))

    def test_buyer_must_say_buys(self):
        a = r1_answer("P01", FEATURES)
        del a["buys"]
        self.assertIn("'buys'", self.ok(a))

    def test_user_answer_needs_its_fields(self):
        a = r1_answer("P01", FEATURES, "user")
        del a["would_ask_parent"]
        self.assertIn("would_ask_parent", self.ok(a, dtype="user"))

    def test_user_scale_range(self):
        a = r1_answer("P01", FEATURES, "user")
        a["wants_it"] = 6
        self.assertIn("'wants_it' must be an integer 1-5", self.ok(a, dtype="user"))

    def test_influencer_answer(self):
        a = r1_answer("P01", FEATURES, "influencer")
        self.assertIsNone(self.ok(a, dtype="influencer"))
        a["concerns"] = " "
        self.assertIn("'concerns' is empty", self.ok(a, dtype="influencer"))

    def test_role_answer_must_match_type(self):
        self.assertIn("'buys'", self.ok(r1_answer("P01", FEATURES, "user"), dtype="buyer"))

    def test_feature_value_must_be_1_to_5_integer(self):
        a = r1_answer("P01", FEATURES, "user")
        a["feature_reactions"][0]["value"] = 6
        self.assertIn("'value' must be an integer 1-5", self.ok(a, dtype="user"))
        a["feature_reactions"][0]["value"] = True
        self.assertIn("'value' must be an integer 1-5", self.ok(a, dtype="user"))

    def test_understood_must_be_bool_and_comment_filled(self):
        a = r1_answer("P01", FEATURES, "user")
        a["feature_reactions"][0]["understood"] = "yes"
        self.assertIn("'understood'", self.ok(a, dtype="user"))
        a = r1_answer("P01", FEATURES, "user")
        a["feature_reactions"][1]["comment"] = "  "
        self.assertIn("'comment' is empty", self.ok(a, dtype="user"))

    def test_every_feature_needs_a_reaction(self):
        a = r1_answer("P01", FEATURES, "user")
        a["feature_reactions"] = a["feature_reactions"][:1]
        self.assertIn("no reaction to features: F2", self.ok(a, dtype="user"))

    def test_at_most_three_questions(self):
        a = r1_answer("P01", FEATURES, "user")
        a["questions"] = ["a?", "b?", "c?", "d?"]
        self.assertIn("at most 3", self.ok(a, dtype="user"))

    def test_r2_changed_mind_needs_reason(self):
        a = r2_answer("P01", FEATURES, "user", changed=True)
        a["why_changed"] = ""
        self.assertIn("why_changed", self.ok(a, dtype="user", rnd="2"))

    def test_task_checks(self):
        card = {"id": "P01", "decision_type": "user", "income": 5000}
        t = task_answer("P01", FEATURES, stuck=True)
        self.assertIsNone(panel.answer_problem(t, card, FEATURES, "task", None))
        t["tasks"][0]["stuck_step"] = 5
        self.assertIn("checkpoint number 1-2", panel.answer_problem(t, card, FEATURES, "task", None))
        t = task_answer("P01", FEATURES)
        t["tasks"][0]["stuck_step"] = 1
        self.assertIn("completed but stuck_step", panel.answer_problem(t, card, FEATURES, "task", None))
        t = task_answer("P01", FEATURES)
        t["tasks"] = t["tasks"][:1]
        self.assertIn("no task result for: F2", panel.answer_problem(t, card, FEATURES, "task", None))


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 3, 7, False)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_save_refuses_invalid_and_files_valid(self):
        features = panel.load_inputs(self.d)[2]
        card = cards_of(self.d)[0]
        with self.assertRaises(panel.PanelError):
            panel.cmd_save(self.d, "1", card["id"], '{"id": "%s", "buys": "maybe"}' % card["id"])
        self.assertFalse(os.path.exists(panel.answer_path(self.d, "1", card["id"])))
        reply = "Here it is:\n" + json.dumps(r1_answer(card["id"], features, card["decision_type"]))
        if card["decision_type"] == "buyer":
            reply = "Here it is:\n" + json.dumps(r1_answer(card["id"], features, "buyer", price=price_of_project(self.d),
                                                           income=card["income"]))
        self.assertTrue(os.path.exists(panel.cmd_save(self.d, "1", card["id"], reply)))

    def test_save_refuses_unknown_persona(self):
        with self.assertRaisesRegex(panel.PanelError, "no persona P99"):
            panel.cmd_save(self.d, "1", "P99", "{}")


class AnswersMdTests(unittest.TestCase):
    def test_parses_only_filled_sections(self):
        tmp, d = make_project()
        try:
            with open(os.path.join(d, "qa", "answers.md"), "w", encoding="utf-8") as fh:
                fh.write("# My answers\n\n### Q1\n\nYes it works offline.\n\n### Q2\n\n\n### Q3\n\nSix hours.\n")
            self.assertEqual(panel.parse_answers_md(d), {"Q1": "Yes it works offline.", "Q3": "Six hours."})
        finally:
            shutil.rmtree(tmp)


class PersonaCountTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_default_is_100_and_quick_is_20(self):
        self.assertEqual((panel.DEFAULT_N, panel.QUICK_N), (100, 20))
        with redirect_stdout(io.StringIO()):
            panel.main(["init", "--dir", self.d])
        self.assertEqual(len(cards_of(self.d)), 100)
        with redirect_stdout(io.StringIO()):
            panel.main(["init", "--dir", self.d, "--quick", "--force"])
        self.assertEqual(len(cards_of(self.d)), 20)

    def test_any_n_is_accepted(self):
        for n in (5, 50, 200):
            with redirect_stdout(io.StringIO()):
                panel.main(["init", "--dir", self.d, "--n", str(n), "--force"])
            self.assertEqual(len(cards_of(self.d)), n)

    def test_n_below_role_count_is_refused_and_keeps_answers(self):
        with redirect_stdout(io.StringIO()):
            panel.main(["init", "--dir", self.d, "--n", "5", "--force"])
        marker = panel.answer_path(self.d, "1", "P01")
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("{}")
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(panel.PanelError, "each role needs"):
            panel.cmd_init(self.d, 2, 7, True)
        self.assertTrue(os.path.exists(marker))


class InputTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_todo_text_blocks_run(self):
        with open(os.path.join(self.d, "product.md"), "a", encoding="utf-8") as fh:
            fh.write("\nTODO finish this")
        with self.assertRaisesRegex(panel.PanelError, "TODO"):
            panel.load_inputs(self.d)

    def test_feature_needs_steps(self):
        p = os.path.join(self.d, "features.json")
        feats = read_json(p)
        feats["features"][0]["steps"] = []
        write_json(p, feats)
        with self.assertRaisesRegex(panel.PanelError, "needs 'steps'"):
            panel.load_inputs(self.d)

    def test_role_needs_decision_type(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        del c["roles"][0]["decision_type"]
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "decision_type"):
            panel.load_inputs(self.d)


if __name__ == "__main__":
    unittest.main()
