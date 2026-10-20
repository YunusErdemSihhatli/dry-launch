import json
import os
import re
import shutil
import unittest

from helpers import make_project, r1_answer, r2_answer, task_answer, read_json, read_text, write_json

import panel

FEATURES = [{"id": "F1", "name": "a", "what": "b", "steps": ["s1", "s2"]},
            {"id": "F2", "name": "c", "what": "d", "steps": ["s1"]}]


class DealTests(unittest.TestCase):
    def test_quota_is_exact_and_fair(self):
        self.assertEqual(panel.quota([{"share": 0.6}, {"share": 0.4}], 5), [3, 2])
        for n in range(1, 40):
            self.assertEqual(sum(panel.quota([{"share": 0.3}, {"share": 0.3}, {"share": 0.4}], n)), n)

    def test_same_seed_same_cards_different_seed_differs(self):
        customer = {"roles": [{"name": "A", "decision_type": "buyer", "share": 1, "age": [20, 30]}],
                    "objections": ["x", "y", "z"]}
        self.assertEqual(panel.deal(customer, 10, 7), panel.deal(customer, 10, 7))
        self.assertNotEqual(panel.deal(customer, 10, 7), panel.deal(customer, 10, 8))

    def test_init_deals_roles_with_decision_types(self):
        tmp, d = make_project()
        try:
            panel.cmd_init(d, 10, 7, False)
            cards, seed = panel.load_cards(d)
            self.assertEqual(len(cards), 10)
            self.assertEqual(seed, 7)
            types = [c["decision_type"] for c in cards]
            self.assertEqual(types.count("buyer"), 4)
            self.assertEqual(types.count("user"), 4)
            self.assertEqual(types.count("influencer"), 2)
            self.assertTrue(os.path.exists(os.path.join(d, "personas", "P01.md")))
        finally:
            shutil.rmtree(tmp)


class IncomeTierTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_tiers_set_income_bounds_and_names(self):
        panel.cmd_init(self.d, 100, 7, False)
        cards = panel.load_cards(self.d)[0]
        bounds = {"low": (500, 1500), "middle": (3000, 5000), "high": (10000, 20000)}
        for c in cards:
            if c["decision_type"] in ("buyer", "influencer"):
                lo, hi = bounds[c["income_tier"]]
                self.assertTrue(lo <= c["income"] <= hi, (c["id"], c["income"]))
            else:
                self.assertIsNone(c["income_tier"])

    def test_tier_shares_are_respected_within_a_role(self):
        panel.cmd_init(self.d, 100, 7, False)
        buyers = [c for c in panel.load_cards(self.d)[0] if c["decision_type"] == "buyer"]
        self.assertEqual(len(buyers), 40)
        counts = {t: sum(1 for c in buyers if c["income_tier"] == t) for t in ("low", "middle", "high")}
        self.assertEqual(counts, {"low": 12, "middle": 20, "high": 8})

    def test_role_without_tiers_uses_its_income_range(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["roles"][0].pop("income_tiers")
        c["roles"][0]["income"] = [2000, 2500]
        write_json(p, c)
        panel.cmd_init(self.d, 10, 7, False)
        buyers = [x for x in panel.load_cards(self.d)[0] if x["decision_type"] == "buyer"]
        self.assertTrue(all(2000 <= x["income"] <= 2500 and x["income_tier"] is None for x in buyers))

    def test_bad_tier_is_refused(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["roles"][0]["income_tiers"][0]["income"] = [5000, 1000]
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "must be \\[low, high\\]"):
            panel.load_inputs(self.d)


class PersonaCountTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_default_is_100_and_quick_is_20(self):
        self.assertEqual((panel.DEFAULT_N, panel.QUICK_N), (100, 20))
        panel.main(["init", "--dir", self.d])
        self.assertEqual(len(panel.load_cards(self.d)[0]), 100)
        panel.main(["init", "--dir", self.d, "--quick", "--force"])
        self.assertEqual(len(panel.load_cards(self.d)[0]), 20)

    def test_any_n_is_accepted(self):
        for n in (5, 50, 200):
            panel.main(["init", "--dir", self.d, "--n", str(n), "--force"])
            self.assertEqual(len(panel.load_cards(self.d)[0]), n)

    def test_n_below_role_count_is_refused_and_keeps_answers(self):
        panel.main(["init", "--dir", self.d, "--n", "5", "--force"])
        marker = panel.answer_path(self.d, "1", "P01")
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("{}")
        self.assertEqual(panel.main(["init", "--dir", self.d, "--n", "2", "--force"]), 2)
        self.assertTrue(os.path.exists(marker))


class IncomeRoundingTests(unittest.TestCase):
    def test_small_incomes_are_not_rounded_to_zero(self):
        self.assertEqual(panel.round_income(500.0), 500)
        self.assertEqual(panel.round_income(1234.0), 1200)
        self.assertEqual(panel.round_income(49999.0), 50000)
        for x in range(500, 20000, 137):
            self.assertGreater(panel.round_income(float(x)), 0)


class AffordabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 10, 7, False)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_buyer_brief_states_price_share_of_monthly_income(self):
        panel.cmd_briefs(self.d, "1", 10)
        buyer = next(c for c in panel.load_cards(self.d)[0] if c["decision_type"] == "buyer" and c["income"])
        text = read_text(os.path.join(self.d, "briefs", "r1", buyer["id"] + ".md"))
        share = 100.0 * read_json(os.path.join(self.d, "customer.json"))["price"] / buyer["income"]
        self.assertIn("about %.0f%% of your monthly income" % share, text)

    def test_user_brief_has_no_price_share(self):
        panel.cmd_briefs(self.d, "1", 10)
        user = next(c for c in panel.load_cards(self.d)[0] if c["decision_type"] == "user")
        self.assertNotIn("of your monthly income", read_text(os.path.join(self.d, "briefs", "r1", user["id"] + ".md")))

    def test_card_shows_monthly_net_income(self):
        buyer = next(c for c in panel.load_cards(self.d)[0] if c["decision_type"] == "buyer")
        self.assertIn("per month, net", read_text(os.path.join(self.d, "personas", buyer["id"] + ".md")))

    def test_bad_price_is_refused(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["price"] = "1499 TL"
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "'price' must be a positive number"):
            panel.load_inputs(self.d)


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

    def test_price_detection(self):
        self.assertTrue(panel.price_enabled("Price: 1499 TL, one-off."))
        self.assertTrue(panel.price_enabled("Only $9 a month"))
        self.assertTrue(panel.price_enabled("Costs 25 USD"))
        self.assertFalse(panel.price_enabled("Free to try. No card needed."))


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 10, 7, False)
        self.cards = panel.load_cards(self.d)[0]
        self.by_type = {}
        for c in self.cards:
            self.by_type.setdefault(c["decision_type"], c)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def brief(self, rnd, pid):
        return read_text(os.path.join(self.d, "briefs", "r" + rnd, pid + ".md"))

    def test_buyer_brief_has_price_block_user_does_not(self):
        panel.cmd_briefs(self.d, "1", 10)
        buyer = self.by_type["buyer"]["id"]
        user = self.by_type["user"]["id"]
        self.assertIn("price_too_cheap", self.brief("1", buyer))
        self.assertNotIn("price_too_cheap", self.brief("1", user))
        self.assertNotIn("=== PRICE ===", self.brief("1", user))

    def test_schema_matches_role(self):
        panel.cmd_briefs(self.d, "1", 10)
        self.assertIn('"wants_it"', self.brief("1", self.by_type["user"]["id"]))
        self.assertIn('"would_ask_parent"', self.brief("1", self.by_type["user"]["id"]))
        self.assertIn('"would_recommend"', self.brief("1", self.by_type["influencer"]["id"]))
        self.assertNotIn('"buys"', self.brief("1", self.by_type["influencer"]["id"]))
        self.assertIn('"buys"', self.brief("1", self.by_type["buyer"]["id"]))

    def test_schema_has_one_reaction_entry_per_feature(self):
        panel.cmd_briefs(self.d, "1", 10)
        text = self.brief("1", "P02")
        self.assertEqual(len(re.findall(r'"feature": "F1"', text)), 1)
        self.assertEqual(len(re.findall(r'"feature": "F2"', text)), 1)

    def test_brief_tone_is_neutral(self):
        panel.cmd_briefs(self.d, "1", 10)
        text = self.brief("1", self.by_type["buyer"]["id"])
        self.assertIn("Both yes and no are useful answers", text)
        self.assertNotIn("Politeness", text)

    def test_money_line_is_buyer_only(self):
        panel.cmd_briefs(self.d, "1", 10)
        buyer = self.brief("1", self.by_type["buyer"]["id"])
        user = self.brief("1", self.by_type["user"]["id"])
        self.assertIn("your own money", buyer)
        self.assertNotIn("your own money", user)
        self.assertIn("whether you would actually play with it", user)

    def test_custom_names_list_is_used(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        c["names"] = ["Zara", "Ilo"]
        write_json(p, c)
        panel.cmd_init(self.d, 4, 7, True)
        names = {x["name"] for x in panel.load_cards(self.d)[0]}
        self.assertEqual(names, {"Zara", "Ilo", "Zara 2", "Ilo 2"})

    def test_brief_only_names_its_own_persona(self):
        panel.cmd_briefs(self.d, "1", 10)
        text = self.brief("1", "P03")
        self.assertEqual(set(re.findall(r"\bP\d\d\b", text)), {"P03"})

    def test_income_line_carries_currency(self):
        panel.cmd_briefs(self.d, "1", 10)
        with_income = [c for c in self.cards if c["income"]][0]
        self.assertRegex(self.brief("1", with_income["id"]), r"monthly net income is about [\d,.]+ USD")

    def test_priced_product_needs_currency(self):
        p = os.path.join(self.d, "customer.json")
        c = read_json(p)
        del c["currency"]
        write_json(p, c)
        with self.assertRaisesRegex(panel.PanelError, "needs 'currency'"):
            panel.cmd_briefs(self.d, "1", 10)

    def test_task_round_refuses_without_screens(self):
        for f in panel.screens_list(self.d):
            os.remove(f)
        with self.assertRaisesRegex(panel.PanelError, "needs screenshots"):
            panel.cmd_briefs(self.d, "task", 10)
        open(os.path.join(self.d, "screens", "home.png"), "wb").close()
        panel.cmd_briefs(self.d, "task", 10)
        text = read_text(os.path.join(self.d, "briefs", "task", "P01.md"))
        self.assertIn("Checkpoints, in order", text)
        self.assertIn("1) Open the coding board", text)

    def test_r2_needs_answered_questions(self):
        with self.assertRaisesRegex(panel.PanelError, "no answered questions"):
            panel.cmd_briefs(self.d, "2", 10)

    def test_r2_brief_contains_team_answer_and_own_round1(self):
        for c in self.cards:
            write_json(panel.answer_path(self.d, "1", c["id"]), r1_answer(c["id"], FEATURES, c["decision_type"]))
        write_json(os.path.join(self.d, "qa", "questions.json"), [{"id": "Q1", "text": "How long does the battery last?"}])
        with open(os.path.join(self.d, "qa", "answers.md"), "w", encoding="utf-8") as fh:
            fh.write("### Q1\n\nSix hours on one charge.\n")
        panel.cmd_briefs(self.d, "2", 10)
        text = self.brief("2", "P02")
        self.assertIn("Six hours on one charge.", text)
        self.assertIn('"id": "P02"', text)


class AnswerValidationTests(unittest.TestCase):
    def ok(self, a, dtype="buyer", rnd="1", price=True):
        return panel.answer_problem(a, "P01", FEATURES, rnd, dtype, price)

    def test_valid_buyer_answer_passes(self):
        self.assertIsNone(self.ok(r1_answer("P01", FEATURES)))

    def test_buyer_must_say_buys(self):
        a = r1_answer("P01", FEATURES)
        del a["buys"]
        self.assertIn("'buys'", self.ok(a))

    def test_buyer_price_required_only_when_priced(self):
        a = r1_answer("P01", FEATURES, price=False)
        self.assertIn("price_too_cheap", self.ok(a, price=True))
        self.assertIsNone(self.ok(a, price=False))

    def test_user_answer_needs_its_fields_and_no_price(self):
        a = r1_answer("P01", FEATURES, "user")
        self.assertIsNone(self.ok(a, dtype="user", price=True))
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
        a = r1_answer("P01", FEATURES, "user")
        self.assertIn("'buys'", self.ok(a, dtype="buyer"))

    def test_feature_value_must_be_1_to_5_integer(self):
        a = r1_answer("P01", FEATURES)
        a["feature_reactions"][0]["value"] = 6
        self.assertIn("'value' must be an integer 1-5", self.ok(a))
        a["feature_reactions"][0]["value"] = True
        self.assertIn("'value' must be an integer 1-5", self.ok(a))

    def test_understood_must_be_bool_and_comment_filled(self):
        a = r1_answer("P01", FEATURES)
        a["feature_reactions"][0]["understood"] = "yes"
        self.assertIn("'understood'", self.ok(a))
        a = r1_answer("P01", FEATURES)
        a["feature_reactions"][1]["comment"] = "  "
        self.assertIn("'comment' is empty", self.ok(a))

    def test_missing_field_is_optional_text(self):
        a = r1_answer("P01", FEATURES)
        a["feature_reactions"][0]["missing"] = "an export button"
        self.assertIsNone(self.ok(a))

    def test_every_feature_needs_a_reaction(self):
        a = r1_answer("P01", FEATURES)
        a["feature_reactions"] = a["feature_reactions"][:1]
        self.assertIn("no reaction to features: F2", self.ok(a))

    def test_at_most_three_questions(self):
        a = r1_answer("P01", FEATURES)
        a["questions"] = ["a?", "b?", "c?", "d?"]
        self.assertIn("at most 3", self.ok(a))

    def test_r2_changed_mind_needs_reason(self):
        a = r2_answer("P01", FEATURES, changed=True)
        a["why_changed"] = ""
        self.assertIn("why_changed", self.ok(a, rnd="2"))

    def test_task_checks(self):
        t = task_answer("P01", FEATURES, stuck=True)
        self.assertIsNone(self.ok(t, rnd="task"))
        t["tasks"][0]["stuck_step"] = 5
        self.assertIn("checkpoint number 1-2", self.ok(t, rnd="task"))
        t = task_answer("P01", FEATURES)
        t["tasks"][0]["stuck_step"] = 1
        self.assertIn("completed but stuck_step", self.ok(t, rnd="task"))
        t = task_answer("P01", FEATURES)
        t["tasks"] = t["tasks"][:1]
        self.assertIn("no task result for: F2", self.ok(t, rnd="task"))


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 3, 7, False)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_save_refuses_invalid_and_files_valid(self):
        features = panel.load_inputs(self.d)[2]
        with self.assertRaises(panel.PanelError):
            panel.cmd_save(self.d, "1", "P01", '{"id": "P01", "buys": "maybe"}')
        self.assertFalse(os.path.exists(panel.answer_path(self.d, "1", "P01")))
        cards = panel.load_cards(self.d)[0]
        dtype = cards[0]["decision_type"]
        reply = "Here it is:\n" + json.dumps(r1_answer("P01", features, dtype))
        self.assertTrue(os.path.exists(panel.cmd_save(self.d, "1", "P01", reply)))

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


if __name__ == "__main__":
    unittest.main()
