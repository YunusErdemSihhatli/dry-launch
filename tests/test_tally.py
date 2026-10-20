import os
import shutil
import unittest

from helpers import make_project, r1_answer, r2_answer, task_answer, read_json, read_text, write_json

import panel
import tally


class RecommendTests(unittest.TestCase):
    def stats(self, value, complexity, understood):
        return {"avg_value": value, "avg_complexity": complexity, "understood": understood}

    def test_keep(self):
        self.assertEqual(tally.recommend(self.stats(4.2, 2.0, 0.9)), "keep")

    def test_drop_when_value_low(self):
        self.assertEqual(tally.recommend(self.stats(2.0, 1.0, 1.0)), "drop")

    def test_improve_in_between(self):
        self.assertEqual(tally.recommend(self.stats(3.0, 2.0, 0.9)), "improve")
        self.assertEqual(tally.recommend(self.stats(4.5, 4.5, 0.9)), "improve")
        self.assertEqual(tally.recommend(self.stats(4.5, 2.0, 0.5)), "improve")


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.d = make_project()
        panel.cmd_init(self.d, 10, 7, False)
        self.features = panel.load_inputs(self.d)[2]
        self.cards = panel.load_cards(self.d)[0]

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, rnd, obj):
        write_json(panel.answer_path(self.d, rnd, obj["id"]), obj)

    def fill_r1(self, buys_every=3):
        for i, c in enumerate(self.cards):
            buys = (i % buys_every != 0)
            self.write("1", r1_answer(c["id"], self.features, c["decision_type"], buys=buys))

    def fill_r2(self, changed_id=None):
        for c in self.cards:
            self.write("2", r2_answer(c["id"], self.features, c["decision_type"], changed=(c["id"] == changed_id)))

    def report(self):
        return read_text(os.path.join(self.d, "report.md"))

    # ── clustering handoff ──────────────────────────────────────────────────────
    def test_cluster_inputs_depend_on_role(self):
        self.fill_r1()
        rows = panel.load_round(self.d, "1")[0]
        themes = tally.cluster_inputs(rows, "themes")
        kinds = {x["kind"] for x in themes}
        self.assertEqual(kinds, {"reason", "objection", "concern"})
        self.assertFalse([x for x in themes if x["persona"] in
                          {c["id"] for c in self.cards if c["decision_type"] == "user"}])
        questions = tally.cluster_inputs(rows, "questions")
        self.assertEqual(len(questions), 10)

    def test_prepare_then_apply_questions(self):
        self.fill_r1()
        tally.cmd_prepare(self.d, "questions")
        raw = read_json(os.path.join(self.d, "qa", "questions_raw.json"))
        refs = [x["ref"] for x in raw]
        clusters = [{"text": "How long does the battery last?", "members": refs[:7]},
                    {"text": "Is it safe?", "members": refs[7:]}]
        write_json(os.path.join(self.d, "qa", "questions_clusters.json"), clusters)
        tally.cmd_apply(self.d, "questions", 10)
        qs = read_json(os.path.join(self.d, "qa", "questions.json"))
        self.assertEqual([q["id"] for q in qs], ["Q1", "Q2"])
        self.assertEqual(qs[0]["count"], 7)
        self.assertTrue(os.path.exists(os.path.join(self.d, "qa", "answers.md")))

    def test_apply_rejects_unknown_duplicate_and_uncovered(self):
        self.fill_r1()
        tally.cmd_prepare(self.d, "themes")
        raw = read_json(os.path.join(self.d, "qa", "themes_raw.json"))
        path = os.path.join(self.d, "qa", "themes_clusters.json")
        ref = raw[0]["ref"]
        write_json(path, [{"text": "x", "members": ["P99-reason"]}])
        with self.assertRaisesRegex(panel.PanelError, "is not in themes_raw"):
            tally.cmd_apply(self.d, "themes", 10)
        write_json(path, [{"text": "x", "members": [ref]}, {"text": "y", "members": [ref]}])
        with self.assertRaisesRegex(panel.PanelError, "two clusters"):
            tally.cmd_apply(self.d, "themes", 10)
        write_json(path, [{"text": "x", "members": [ref]}])
        with self.assertRaisesRegex(panel.PanelError, "in no cluster"):
            tally.cmd_apply(self.d, "themes", 10)

    def test_themes_apply_writes_themes(self):
        self.fill_r1()
        tally.cmd_prepare(self.d, "themes")
        raw = read_json(os.path.join(self.d, "qa", "themes_raw.json"))
        write_json(os.path.join(self.d, "qa", "themes_clusters.json"),
                   [{"text": "screen time worry", "members": [x["ref"] for x in raw]}])
        tally.cmd_apply(self.d, "themes", 10)
        ts = read_json(os.path.join(self.d, "qa", "themes.json"))
        self.assertEqual(ts[0]["count"], len(raw))

    # ── report ──────────────────────────────────────────────────────────────────
    def test_purchase_rate_counts_buyers_only(self):
        # every user and influencer says yes, every buyer says no: buyer rate must be 0%
        for c in self.cards:
            self.write("1", r1_answer(c["id"], self.features, c["decision_type"],
                                      buys=(c["decision_type"] != "buyer")))
        tally.cmd_results(self.d)
        self.assertIn("**Round 1, buyers:** 0 buy", self.report())

    def test_report_sections_and_role_metrics(self):
        self.fill_r1()
        tally.cmd_results(self.d)
        text = self.report()
        for heading in ("## By role", "## Features", "## Why buyers pass", "## Task test", "## Price range",
                        "## Warnings: read before you act", "### Three riskiest assumptions to verify with real users",
                        "## Missing answers"):
            self.assertIn(heading, text)
        self.assertIn("wants it", text)
        self.assertIn("would recommend", text)
        self.assertIn("buys", text)
        self.assertIn("The purchase rate is for buyers only", text)
        self.assertIn("Buy rate is an upper bound", text)

    def test_price_range_uses_buyers_only(self):
        self.fill_r1()
        tally.cmd_results(self.d)
        self.assertIn("buyers only", self.report())

    def test_task_not_run_yet_and_round2_not_run_yet(self):
        self.fill_r1()
        tally.cmd_results(self.d)
        text = self.report()
        self.assertIn("- round 2: not run yet", text)
        self.assertIn("- task test: not run yet", text)
        self.assertNotIn("## Round 2: what moved", text)

    def test_round2_section_when_present(self):
        self.fill_r1()
        self.fill_r2(changed_id="P02")
        tally.cmd_results(self.d)
        text = self.report()
        self.assertIn("## Round 2: what moved", text)
        self.assertIn("Changed their mind: 1 of 10", text)

    def test_task_section_when_present(self):
        self.fill_r1()
        for c in self.cards:
            self.write("task", task_answer(c["id"], self.features, stuck=(c["id"] == "P01")))
        tally.cmd_results(self.d)
        text = self.report()
        self.assertIn("### F1 Block coding: 9 of 10 reached the goal", text)
        self.assertIn("stuck at checkpoint 1", text)

    def test_missing_features_are_listed(self):
        self.fill_r1()
        a = panel.load_round(self.d, "1")[0][0]
        path = panel.answer_path(self.d, "1", a["id"])
        obj = read_json(path)
        obj["feature_reactions"][0]["missing"] = "an export to PDF"
        write_json(path, obj)
        tally.cmd_results(self.d)
        self.assertIn('"an export to PDF"', self.report())

    def test_most_common_objection_counted_by_reason_code(self):
        for c in self.cards:
            self.write("1", r1_answer(c["id"], self.features, c["decision_type"],
                                      buys=(c["decision_type"] != "buyer")))
        tally.cmd_results(self.d)
        text = self.report()
        self.assertIn("| price |", text)
        self.assertIn("the main reason buyers pass, \"price\"", text)


if __name__ == "__main__":
    unittest.main()
