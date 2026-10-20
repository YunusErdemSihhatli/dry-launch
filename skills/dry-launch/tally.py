#!/usr/bin/env python3
"""dry-launch tally: prepares the clustering inputs and writes the press conference report.
Standard library only. Imports panel.py and pricing.py from this folder.

    python3 tally.py cluster prepare --what questions|themes [--dir launch]
    python3 tally.py cluster apply   --what questions|themes [--dir launch] [--top 10]
    python3 tally.py results         [--dir launch]

Semantic clustering is NOT done here. A Sonnet subagent reads qa/<what>_raw.json and writes
qa/<what>_clusters.json (see SKILL.md). This script prepares the data and checks the clusters.

Every number is counted from the answer files. Nothing here answers for a persona.
Purchase rate and price range come from buyers only.
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

import panel
import pricing

# Feature recommendation thresholds, applied to the averages over all personas.
DROP_VALUE = 2.5          # avg value at or below this: drop
KEEP_VALUE = 3.5          # avg value at or above this ...
KEEP_COMPLEXITY = 3.0     # ... and avg complexity at or below this ...
KEEP_UNDERSTOOD = 0.7     # ... and at least this share understood it: keep
MISSING_SHARE = 0.3       # at least this share named something missing: say so next to the verdict
TOP_QUESTIONS = 10


# ── features ────────────────────────────────────────────────────────────────────
def recommend(stats):
    """keep / improve / drop, derived from the persona scores only."""
    if stats["avg_value"] <= DROP_VALUE:
        return "drop"
    if (stats["avg_value"] >= KEEP_VALUE and stats["avg_complexity"] <= KEEP_COMPLEXITY
            and stats["understood"] >= KEEP_UNDERSTOOD):
        return "keep"
    return "improve"


def feature_stats(features, rows):
    """Aggregate each feature's reactions. A feature with "for" is scored only from those roles; without it,
    from every role. Per-role average values are kept for the breakdown table."""
    out = []
    for f in features:
        all_reacts = [(r, x) for r in rows for x in r["feature_reactions"] if x["feature"] == f["id"]]
        if not all_reacts:
            continue
        per_role = {}
        for dtype in panel.DECISION_TYPES:
            vals = [x["value"] for r, x in all_reacts if r["decision_type"] == dtype]
            per_role[dtype] = sum(vals) / len(vals) if vals else None
        allowed = f.get("for") or list(panel.DECISION_TYPES)
        reacts = [(r, x) for r, x in all_reacts if r["decision_type"] in allowed]
        if not reacts:
            out.append({"feature": f, "n": 0, "scored_for": allowed, "per_role": per_role,
                        "recommendation": "n/a (no %s in this panel)" % "/".join(allowed), "reacts": [],
                        "missing": [], "missing_share": 0.0, "avg_value": 0.0, "avg_complexity": 0.0,
                        "understood": 0.0})
            continue
        n = len(reacts)
        missing = [(r["id"], x["missing"].strip()) for r, x in reacts if x.get("missing", "").strip()]
        st = {
            "feature": f,
            "n": n,
            "scored_for": allowed,
            "per_role": per_role,
            "avg_value": sum(x["value"] for _, x in reacts) / n,
            "avg_complexity": sum(x["complexity"] for _, x in reacts) / n,
            "understood": sum(1 for _, x in reacts if x["understood"]) / n,
            "missing": missing,
            "missing_share": len(missing) / n,
            "reacts": reacts,
        }
        st["recommendation"] = recommend(st)
        out.append(st)
    return out


# ── clustering (questions and themes) ───────────────────────────────────────────
def cluster_inputs(rows, what):
    """Raw items for Sonnet to cluster: a list of {ref, persona, kind, text}."""
    raw = []
    if what == "questions":
        for r in rows:
            for k, q in enumerate(r.get("questions", []), 1):
                raw.append({"ref": "%s-%d" % (r["id"], k), "persona": r["id"], "kind": "question", "text": q.strip()})
        return raw
    for r in rows:
        if r["decision_type"] == "buyer":
            if str(r.get("reason", "")).strip():
                raw.append({"ref": "%s-reason" % r["id"], "persona": r["id"], "kind": "reason",
                            "text": r["reason"].strip()})
            if str(r.get("top_objection", "")).strip():
                raw.append({"ref": "%s-objection" % r["id"], "persona": r["id"], "kind": "objection",
                            "text": r["top_objection"].strip()})
        if r["decision_type"] == "influencer" and str(r.get("concerns", "")).strip():
            raw.append({"ref": "%s-concern" % r["id"], "persona": r["id"], "kind": "concern",
                        "text": r["concerns"].strip()})
    return raw


def cmd_prepare(d, what):
    rows, skipped = panel.load_round(d, "1")
    if not rows:
        raise panel.PanelError("no round 1 answers yet: run briefs --round 1, then check --round 1")
    raw = cluster_inputs(rows, what)
    if not raw:
        raise panel.PanelError("nothing to cluster for %s" % what)
    path = os.path.join(d, "qa", "%s_raw.json" % what)
    panel.write_json(path, raw)
    print("%d %s items -> %s. Next: Sonnet subagent writes qa/%s_clusters.json, then cluster apply --what %s" % (
        len(raw), what, path, what, what))
    if skipped:
        print("note: %d round-1 answers invalid and not counted" % len(skipped))


def cmd_apply(d, what, top):
    raw = panel.load_json(os.path.join(d, "qa", "%s_raw.json" % what))
    refs = {x["ref"]: x for x in raw}
    clusters = panel.load_json(os.path.join(d, "qa", "%s_clusters.json" % what))
    if not isinstance(clusters, list) or not clusters:
        raise panel.PanelError("qa/%s_clusters.json must be a non-empty list" % what)
    seen = set()
    for c in clusters:
        if not isinstance(c, dict) or not str(c.get("text", "")).strip() or not isinstance(c.get("members"), list):
            raise panel.PanelError("each cluster needs a 'text' and a 'members' list")
        for m in c["members"]:
            if m not in refs:
                raise panel.PanelError("cluster member %r is not in %s_raw.json" % (m, what))
            if m in seen:
                raise panel.PanelError("%r is in two clusters" % m)
            seen.add(m)
    missing = set(refs) - seen
    if missing:
        raise panel.PanelError("%d items are in no cluster, e.g. %s" % (len(missing), sorted(missing)[0]))
    clusters = sorted(clusters, key=lambda c: -len(c["members"]))
    if what == "questions":
        write_questions(d, clusters[:top], refs)
    else:
        write_themes(d, clusters, refs)


def write_questions(d, clusters, refs):
    qs = []
    for k, c in enumerate(clusters, 1):
        qs.append({
            "id": "Q%d" % k,
            "text": c["text"].strip(),
            "count": len(c["members"]),
            "asked_by": sorted({refs[m]["persona"] for m in c["members"]}),
            "variants": [refs[m]["text"] for m in c["members"]][:5],
        })
    panel.write_json(os.path.join(d, "qa", "questions.json"), qs)
    L = ["# Press conference questions (round 1)", "",
         "The %d most frequent questions, clustered by meaning. Write your answer under the matching "
         "`### Qn` heading in `qa/answers.md`." % len(qs), ""]
    for q in qs:
        L += ["### %s · asked by %d" % (q["id"], q["count"]), "", "> %s" % q["text"], "",
              "Asked by: %s" % ", ".join(q["asked_by"]), ""]
    with open(os.path.join(d, "qa", "questions.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    amd = os.path.join(d, "qa", "answers.md")
    if os.path.exists(amd):
        print("qa/answers.md already exists, left untouched. If question numbers changed, match them by hand.")
    else:
        A = ["# My answers", "", "Write your answer under each question heading. Empty answers do not go to round 2.", ""]
        for q in qs:
            A += ["### %s" % q["id"], "", ""]
        with open(amd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(A) + "\n")
    print("%d questions -> qa/questions.md and qa/answers.md" % len(qs))


def write_themes(d, clusters, refs):
    ts = []
    for k, c in enumerate(clusters, 1):
        ts.append({
            "id": "T%d" % k,
            "text": c["text"].strip(),
            "count": len(c["members"]),
            "kinds": dict(Counter(refs[m]["kind"] for m in c["members"])),
            "personas": sorted({refs[m]["persona"] for m in c["members"]}),
        })
    panel.write_json(os.path.join(d, "qa", "themes.json"), ts)
    print("%d themes -> qa/themes.json" % len(ts))


# ── results ─────────────────────────────────────────────────────────────────────
def pct(v):
    return "%.0f%%" % (v * 100)


def people(k):
    return "1 person" if k == 1 else "%d people" % k


def quote(s):
    return (s or "").replace("|", "/").replace("\n", " ").strip()


def buyers(rows):
    """Buyers whose answers count for buy rates and price ranges. Misunderstood buyers are excluded
    here; their feature scores still count (feature_stats uses every persona)."""
    return [r for r in rows if r["decision_type"] == "buyer" and not r.get("misunderstood")]


def buy_rate(rows):
    b = buyers(rows)
    return (sum(1 for r in b if r["buys"]) / len(b)) if b else None


def role_metric(rows):
    """One summary line per role, by decision type."""
    if not rows:
        return "-"
    dtype = rows[0]["decision_type"]
    n = len(rows)
    if dtype == "buyer":
        return "buys %s" % pct(sum(1 for r in rows if r["buys"]) / n)
    if dtype == "user":
        return "wants it %.1f/5 · would ask a parent %s · keeps using after a week %s" % (
            sum(r["wants_it"] for r in rows) / n,
            pct(sum(1 for r in rows if r["would_ask_parent"]) / n),
            pct(sum(1 for r in rows if r["would_keep_using_after_week"]) / n))
    return "would recommend %.1f/5" % (sum(r["would_recommend"] for r in rows) / n)


def misread_line(L, r1):
    """How many buyers misread the price or their income. A high share points at the keynote."""
    all_buyers = [r for r in r1 if r["decision_type"] == "buyer"]
    if not all_buyers:
        return
    n = sum(1 for r in all_buyers if r.get("misunderstood"))
    L.append("**Comprehension:** %d of %d buyers misread the price or their income (%s). Misread buyers are kept "
             "for feature scores but left out of the buy rate and the price range. If this is high, the price may "
             "be unclear in the keynote." % (n, len(all_buyers), pct(n / len(all_buyers))))


def section_roles(L, r1, r2):
    L += ["## By role", "",
          "The purchase rate is for buyers only. Users and influencers are scored on their own questions.", "",
          "| role | type | personas | round 1 | round 2 |", "| --- | --- | ---: | --- | --- |"]
    for role in sorted({r["role"] for r in r1}):
        g1 = [r for r in r1 if r["role"] == role]
        g2 = [r for r in r2 if r["role"] == role] if r2 else []
        L.append("| %s | %s | %d | %s | %s |" % (
            role, g1[0]["decision_type"], len(g1), role_metric(g1), role_metric(g2) if g2 else "-"))


def section_features(L, stats):
    L += ["## Features", "",
          "Recommendation is derived from the persona scores of the roles each feature is for (keep: avg value >= %.1f, "
          "avg complexity <= %.1f, understood >= %d%%; drop: avg value <= %.1f; otherwise improve). A feature with no "
          "\"for\" is scored from all roles." % (KEEP_VALUE, KEEP_COMPLEXITY, KEEP_UNDERSTOOD * 100, DROP_VALUE), "",
          "| feature | scored from | value | complexity | understood | said something missing | recommendation |",
          "| --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for s in stats:
        rec = s["recommendation"]
        if s["missing_share"] >= MISSING_SHARE:
            rec += ", add what is missing"
        if s["n"] == 0:
            L.append("| %s %s | %s | - | - | - | - | **%s** |" % (
                s["feature"]["id"], s["feature"]["name"], "/".join(s["scored_for"]), rec))
            continue
        L.append("| %s %s | %s | %.1f | %.1f | %s | %s (%d) | **%s** |" % (
            s["feature"]["id"], s["feature"]["name"], "/".join(s["scored_for"]), s["avg_value"], s["avg_complexity"],
            pct(s["understood"]), pct(s["missing_share"]), len(s["missing"]), rec))
    L += ["", "### Feature value by role", "",
          "Average value (1-5) per role, from all personas, whether or not the role is scored for the feature.", "",
          "| feature | buyer | user | influencer |", "| --- | ---: | ---: | ---: |"]
    for s_ in stats:
        cells = ["-" if s_["per_role"][d] is None else "%.1f" % s_["per_role"][d] for d in panel.DECISION_TYPES]
        L.append("| %s %s | %s |" % (s_["feature"]["id"], s_["feature"]["name"], " | ".join(cells)))
    L += ["", "### Features people say are missing", ""]
    any_missing = False
    for s in stats:
        for pid, text in s["missing"][:5]:
            any_missing = True
            L.append("- %s · %s (%s): \"%s\"" % (s["feature"]["id"], s["feature"]["name"], pid, quote(text)))
    if not any_missing:
        L.append("- none named")
    L += ["", "### Three lowest-value features: what people said", ""]
    for s in sorted(stats, key=lambda s: s["avg_value"])[:3]:
        L.append("**%s %s** (value %.1f)" % (s["feature"]["id"], s["feature"]["name"], s["avg_value"]))
        for r, x in sorted(s["reacts"], key=lambda t: t[1]["value"])[:3]:
            L.append("- %s (%s): \"%s\"" % (r["id"], r["role"], quote(x["comment"])))
        L.append("")


def section_reasons(L, latest):
    b = buyers(latest)
    L += ["## Why buyers pass", "", "| reason | people | in their words |", "| --- | ---: | --- |"]
    byc = defaultdict(list)
    for r in b:
        if not r["buys"]:
            byc[r["reason_code"]].append(r)
    if not byc:
        L.append("| - | 0 | no buyer passes; treat that with suspicion |")
    for code, rs in sorted(byc.items(), key=lambda kv: -len(kv[1])):
        q = " · ".join('"%s" (%s)' % (quote(x["reason"]), x["id"]) for x in rs[:2])
        L.append("| %s | %d | %s |" % (code, len(rs), q))
    L += ["", "## Why buyers buy", "", "| reason | people | in their words |", "| --- | ---: | --- |"]
    byy = defaultdict(list)
    for r in b:
        if r["buys"]:
            byy[r["reason_code"]].append(r)
    for code, rs in sorted(byy.items(), key=lambda kv: -len(kv[1])):
        q = " · ".join('"%s" (%s)' % (quote(x["reason"]), x["id"]) for x in rs[:2])
        L.append("| %s | %d | %s |" % (code, len(rs), q))
    flips = [quote(r.get("would_change_my_mind")) for r in b if not r["buys"] and quote(r.get("would_change_my_mind"))]
    if flips:
        unique = list(dict.fromkeys(flips))
        L += ["", "## What would flip a no", ""] + ["- %s" % f for f in unique[:12]]


def section_round2(L, r1, r2):
    by1 = {r["id"]: r["buys"] for r in buyers(r1)}
    b2 = buyers(r2)
    yes_to_no = [r for r in b2 if by1.get(r["id"]) and not r["buys"]]
    no_to_yes = [r for r in b2 if not by1.get(r["id"]) and r["buys"]]
    changed = [r for r in r2 if r["changed_mind"]]
    L += ["", "## Round 2: what moved", "",
          "Buy counts are for buyers only. Changed minds are counted for every role.", "",
          "- Stayed yes: %d · stayed no: %d" % (
              sum(1 for r in b2 if by1.get(r["id"]) and r["buys"]),
              sum(1 for r in b2 if not by1.get(r["id"]) and not r["buys"])),
          "- Yes to no: %d · no to yes: %d" % (len(yes_to_no), len(no_to_yes)),
          "- Changed their mind: %d of %d personas" % (len(changed), len(r2))]
    for r in (yes_to_no + no_to_yes)[:8]:
        L.append("- %s (%s): \"%s\"" % (r["id"], r["role"], quote(r["why_changed"]) or quote(r["reason"])))


def section_themes(L, d):
    path = os.path.join(d, "qa", "themes.json")
    L += ["## Themes in free-text answers", ""]
    if not os.path.exists(path):
        L.append("Not clustered yet. Run cluster prepare and cluster apply with --what themes.")
        return
    ts = panel.load_json(path)
    L += ["Buyer reasons and objections and influencer concerns, clustered by meaning.", "",
          "| theme | people | from |", "| --- | ---: | --- |"]
    for t in ts:
        src = ", ".join("%s %d" % (k, v) for k, v in sorted(t["kinds"].items()))
        L.append("| %s | %d | %s |" % (t["text"], t["count"], src))


def section_tasks(L, tasks_rows, features):
    """Writes the task section and returns the most-stuck (feature, step) counts."""
    L += ["## Task test", ""]
    by_id = {f["id"]: f for f in features}
    stuck_at = Counter()
    for f in features:
        results = [(r, t) for r in tasks_rows for t in r["tasks"] if t["feature"] == f["id"]]
        if not results:
            continue
        done = sum(1 for _, t in results if t["completed"])
        L += ["### %s %s: %d of %d reached the goal" % (f["id"], f["name"], done, len(results)), ""]
        steps = Counter(t["stuck_step"] for _, t in results if not t["completed"])
        for step, k in steps.most_common():
            stuck_at[(f["id"], step)] += k
            L.append("- stuck at checkpoint %d (\"%s\"): %s" % (step, by_id[f["id"]]["steps"][step - 1], people(k)))
        for r, t in [(r, t) for r, t in results if not t["completed"]][:3]:
            L.append("- %s (%s): \"%s\"" % (r["id"], r["role"], quote(t["why"])))
        L.append("")
    return stuck_at


def section_bands(L, r1, r2, customer):
    """Buy rate and price range for each income band. Buyers only."""
    L += ["## By income band", "",
          "Monthly net household income, from the market's bands. Buyers only.", "",
          "| band | monthly net income | buyers | round 1 buy | round 2 buy | price range (round 1) |",
          "| --- | --- | ---: | --- | --- | --- |"]
    price = panel.price_of(customer)
    for b in customer["market"]["income_bands"]:
        g1 = [r for r in buyers(r1) if r["income_band"] == b["name"]]
        g2 = [r for r in buyers(r2) if r["income_band"] == b["name"]] if r2 else []
        if g1:
            rate1 = "%s" % pct(sum(1 for r in g1 if r["buys"]) / len(g1))
        else:
            rate1 = "-"
        rate2 = "%s" % pct(sum(1 for r in g2 if r["buys"]) / len(g2)) if g2 else "-"
        rng = "not enough answers"
        if price:
            result, _ = pricing.from_answers(g1, panel.PRICE_KEYS)
            if result:
                lo, hi = result["range"]
                rng = "%s to %s %s" % (fmt_amt(lo), fmt_amt(hi), customer["market"]["currency"])
        lo_m, hi_m = b["monthly"]
        L.append("| %s | %s-%s %s | %d | %s | %s | %s |" % (
            b["name"], fmt_amt(lo_m), fmt_amt(hi_m), customer["market"]["currency"], len(g1), rate1, rate2, rng))


def fmt_amt(x):
    return "{:,.0f}".format(x)


def section_price(L, r1):
    result, dropped = pricing.from_answers(buyers(r1), panel.PRICE_KEYS)
    L += ["## Price range (Van Westendorp, simulated, buyers only)", ""]
    L += pricing.report_lines(result, dropped)


def section_warnings(L, r1, r2, stats, stuck_at, features, prices_shown):
    latest = r2 if r2 else r1
    b = buyers(latest)
    rate = buy_rate(latest)
    L += ["## Warnings: read before you act", "",
          "- These are simulated personas from a language model. They find objections and weak spots; they do "
          "not predict real sales.",
          "- Buy rate is an upper bound: %s of buyers in the latest round (%d of %d). Real conversion is lower." % (
              pct(rate) if rate is not None else "n/a", sum(r["buys"] for r in b), len(b)),
          "", "### Three riskiest assumptions to verify with real users", ""]
    risks = []
    lowest = sorted(stats, key=lambda s: s["avg_value"])
    if lowest:
        s = lowest[0]
        risks.append("%s %s is worth building (lowest average value: %.1f of 5)" % (
            s["feature"]["id"], s["feature"]["name"], s["avg_value"]))
    if stuck_at:
        (fid, step), k = stuck_at.most_common(1)[0]
        feat = next(f for f in features if f["id"] == fid)
        risks.append("checkpoint %d of %s (\"%s\") is clear to users (%s got stuck there)" % (
            step, fid, feat["steps"][step - 1], people(k)))
    passes = Counter(r["reason_code"] for r in b if not r["buys"])
    if passes:
        code, k = passes.most_common(1)[0]
        risks.append("the main reason buyers pass, \"%s\" (%s), can be answered by the product" % (code, people(k)))
    if not risks:
        L.append("- not enough answers to name risks yet")
    for i, r in enumerate(risks[:3], 1):
        L.append("%d. %s" % (i, r))
    if prices_shown:
        L.append("- Price: the acceptable range above comes from simulated buyer answers only. Test it with real "
                 "buyers before setting a price.")


def round_status(d, rnd, skipped):
    """'not run yet' when no answer file exists for the round, otherwise the missing ids."""
    cards, _ = panel.load_cards(d)
    if not any(os.path.exists(panel.answer_path(d, rnd, c["id"])) for c in cards):
        return "not run yet"
    return ", ".join("%s (%s)" % s for s in skipped) if skipped else "none"


def cmd_results(d):
    r1, sk1 = panel.load_round(d, "1")
    if not r1:
        raise panel.PanelError("no round 1 answers yet")
    r2, sk2 = panel.load_round(d, "2")
    tasks_rows, sk3 = panel.load_round(d, "task")
    customer, _, features = panel.load_inputs(d)
    prices_shown = panel.price_of(customer) is not None
    latest = r2 if r2 else r1
    stats = feature_stats(features, latest)

    m = customer["market"]
    L = ["# Press conference report", "",
         "**Market:** %s · currency %s · income: %s (%d), monthly net household income, by band · "
         "confirmed: %s" % (m["country"], m["currency"], m["income_source"], m["income_year"],
                            "yes" if m["confirmed"] else "no"), ""]
    b1 = buyers(r1)
    y1 = sum(r["buys"] for r in b1)
    L.append("**Round 1, buyers:** %d buy · %d pass (%s of %d buyers)." % (
        y1, len(b1) - y1, pct(buy_rate(r1) or 0), len(b1)))
    if r2:
        b2 = buyers(r2)
        y2 = sum(r["buys"] for r in b2)
        L.append("**Round 2, buyers:** %d buy · %d pass (%s of %d buyers)." % (
            y2, len(b2) - y2, pct(buy_rate(r2) or 0), len(b2)))
    L.append("")
    misread_line(L, r1)
    L.append("")
    section_roles(L, r1, r2)
    L.append("")
    section_bands(L, r1, r2, customer)
    L.append("")
    section_features(L, stats)
    L.append("")
    section_reasons(L, latest)
    L.append("")
    if r2:
        section_round2(L, r1, r2)
        L.append("")
    section_themes(L, d)
    L.append("")
    if tasks_rows:
        stuck_at = section_tasks(L, tasks_rows, features)
    else:
        stuck_at = Counter()
        L += ["## Task test", "", "Not run yet."]
    L.append("")
    if prices_shown:
        section_price(L, r1)
        L.append("")
    section_warnings(L, r1, r2, stats, stuck_at, features, prices_shown)

    L += ["", "## Missing answers", ""]
    for label, rnd, sk in (("round 1", "1", sk1), ("round 2", "2", sk2), ("task test", "task", sk3)):
        L.append("- %s: %s" % (label, round_status(d, rnd, sk)))

    out = os.path.join(d, "report.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("report: %s (latest round: %s)" % (out, "2" if r2 else "1"))


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", default="launch", help="project folder (default: launch)")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    cl = sub.add_parser("cluster", parents=[common])
    clsub = cl.add_subparsers(dest="action", required=True)
    prep = clsub.add_parser("prepare", parents=[common])
    prep.add_argument("--what", choices=("questions", "themes"), required=True)
    app = clsub.add_parser("apply", parents=[common])
    app.add_argument("--what", choices=("questions", "themes"), required=True)
    app.add_argument("--top", type=int, default=TOP_QUESTIONS)
    sub.add_parser("results", parents=[common])
    a = ap.parse_args(argv)
    try:
        if a.cmd == "cluster" and a.action == "prepare":
            cmd_prepare(a.dir, a.what)
        elif a.cmd == "cluster":
            cmd_apply(a.dir, a.what, a.top)
        else:
            cmd_results(a.dir)
    except panel.PanelError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
