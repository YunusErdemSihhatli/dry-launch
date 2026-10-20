#!/usr/bin/env python3
"""dry-launch panel: deals persona cards and runs the bookkeeping for every round.
Standard library only, no network.

    python3 panel.py init   [--dir launch] [--n 100 | --quick] [--seed 7] [--force]
    python3 panel.py briefs [--dir launch] --round 1|2|task [--wave 10]
    python3 panel.py check  [--dir launch] --round 1|2|task
    python3 panel.py save   [--dir launch] --round 1|2|task ID < reply.txt
    python3 panel.py status [--dir launch]

Each role in customer.json has a decision_type:
    buyer       pays for it: buys, reason_code, reason, and the four price answers if the product states a price
    user        uses it, does not pay: wants_it, would_ask_parent, would_keep_using_after_week
    influencer  is asked by buyers: would_recommend, concerns
Every role rates every feature. Purchase rate and price range come from buyers only.

Rounds:
    1     keynote: each persona hears the pitch, rates features, answers its role's questions, asks questions
    2     after the team answers the questions: each persona re-decides
    task  task test: each persona walks the features' checkpoints on the screens and records where it gets stuck

Personas answer through subagents that write their own files. This script never writes an
answer for a persona: `save` only files a reply the persona printed.
"""

import argparse
import glob
import json
import os
import random
import re
import shutil
import sys

ROUNDS = ("1", "2", "task")
DEFAULT_N = 100
QUICK_N = 20
DECISION_TYPES = ("buyer", "user", "influencer")
REASONS = ["price", "need", "habit", "trust", "quality", "convenience", "timing", "values", "other"]
TEMPERS = [
    "skeptical, questions everything",
    "curious, likes trying new things",
    "in a hurry, decides fast",
    "frugal, weighs every expense",
    "tech-savvy, adopts early",
    "trusts recommendations, asks friends",
    "indecisive, prefers to postpone",
    "emotional, moved by a good story",
]
NAMES = [
    "Ava", "Liam", "Maya", "Noah", "Zoe", "Ethan", "Priya", "Mateo", "Leah", "Omar", "Ruby", "Kai",
    "Nora", "Felix", "Amara", "Theo", "Mei", "Jonah", "Sara", "Diego", "Isla", "Caleb", "Hana", "Luca",
    "Grace", "Ravi", "Elena", "Owen", "Talia", "Mason", "Lina", "Victor", "Iris", "Dev", "Clara", "Rafael",
    "Ivy", "Tomas", "Lucia", "Ezra", "Sienna", "Quinn", "Yara", "Hugo", "Nia", "Oscar", "Tess", "Emil",
]
PRICE_KEYS = ("price_too_cheap", "price_bargain", "price_expensive", "price_too_expensive")
# A price counts as stated when product.md has a number next to a currency sign or code.
PRICE_RE = re.compile(r"\d[\d.,]*\s*(?:TL|₺|USD|EUR|GBP|\$|€|£)|[$€£₺]\s*\d[\d.,]*")

# Role-specific answer fields per round: (key, kind). Kinds: bool, scale (1-5), reason, text.
FIELDS = {
    "buyer": {
        "1": [("buys", "bool"), ("reason_code", "reason"), ("reason", "text"), ("top_objection", "text")],
        "2": [("buys", "bool"), ("reason_code", "reason"), ("reason", "text")],
    },
    "user": {
        "1": [("wants_it", "scale"), ("would_ask_parent", "bool"), ("would_keep_using_after_week", "bool")],
        "2": [("wants_it", "scale"), ("would_ask_parent", "bool"), ("would_keep_using_after_week", "bool")],
    },
    "influencer": {
        "1": [("would_recommend", "scale"), ("concerns", "text")],
        "2": [("would_recommend", "scale"), ("concerns", "text")],
    },
}
DESCRIPTIONS = {
    "buys": "true or false: would you buy it",
    "reason_code": "one of price / need / habit / trust / quality / convenience / timing / values / other",
    "reason": "why, one or two sentences, in your own voice",
    "top_objection": "what holds you back most right now",
    "wants_it": "a number 1 to 5: how much you want it",
    "would_ask_parent": "true or false: would you ask someone else to buy it for you",
    "would_keep_using_after_week": "true or false: would you still use it after a week",
    "would_recommend": "a number 1 to 5: how likely you are to recommend it to someone who might buy it",
    "concerns": "what you would warn someone about, in your own voice",
}
ROLE_HELP = {
    "buyer": "You are the one who pays. Your answers are about buying it.",
    "user": "You would use it, but you do not pay for it. Your answers are about wanting it and whether you "
            "would ask someone to buy it.",
    "influencer": "You do not buy it yourself, but people ask you about things like this. Your answers are "
                  "about whether you would recommend it.",
}
REACTION_SCHEMA = """    {"feature": "__FID__", "understood": true or false,
     "value": 1 to 5, "complexity": 1 to 5,
     "comment": "what you think of this feature, in your own voice",
     "missing": "what you expected here that the keynote does not offer, or empty"}"""
TASK_SCHEMA = """{
  "id": "__ID__",
  "tasks": [
    {"feature": "F1", "completed": true or false,
     "stuck_step": null if completed, otherwise the number of the checkpoint where you got stuck,
     "why": "why you got stuck there, or why it was easy"}
  ],
  "overall": "one or two sentences on how the whole flow felt"
}"""

PERSONA_HEAD = """You are at a press conference where a product is being launched. First you listen to the
keynote; then, like anyone in the room, you may ask questions. Nobody is steering you. This is a
pre-launch dry run: the team wants to see a real person's reaction before spending money.
Be honest. If you are not interested, say you would not buy it. Politeness is not useful here.
"""

BRIEF_R1 = PERSONA_HEAD + """
=== WHO YOU ARE ===
{name}, {age} years old. Your role: {role}. {role_help}
{income_line}How you decide: {how}
Who decides: {decision}
Personality: {temper}.
{habit_line}The first thing that comes to mind when you hear about a product like this: "{objection}"
=== END ===

=== KEYNOTE ===
{product}
=== END ===

=== FEATURES (rate each one for your role, in your own circumstances) ===
{features}
=== END ===
{price_block}
{screens_line}
Rules:
- Do not assume anything the keynote does not say. Ask about gaps as questions.
- Think about your own life and your own money, not the product in the abstract.
- Give a reaction for every feature. Do not skip any.
- value: how much this feature is worth to you. complexity: how hard it looks to use.

Write the file {out} with your file-writing tool (do not just print it). The content must be ONLY this
JSON, no markdown fence, no other text:
{schema}
"""

BRIEF_R2 = PERSONA_HEAD + """
This is round 2. The product is the same and so are you: {name}, {age} years old, {role}. {role_help}
Who decides: {decision}
How you decide: {how}

In round 1 your own answer was:
{prev}

The team answered the questions from the room. The answers:
{qa}

=== KEYNOTE ===
{product}
=== END ===

=== FEATURES ===
{features}
=== END ===

{screens_line}
Rules:
- Read the answers and re-evaluate your position. You do not have to accept everything.
- If you change your position, say concretely what changed it: which answer convinced you?
- If you were not convinced, stay where you are and say why.
- You do not know what other people said, and you do not need to.

Write the file {out} with your file-writing tool (do not just print it). The content must be ONLY this
JSON, no markdown fence, no other text:
{schema}
"""

BRIEF_TASK = """You are a potential user of this product: {name}, {age} years old, {role}.
How you use things: {how}
Personality: {temper}.

You are doing a usability walkthrough. For each task below, you try to reach the goal using ONLY the
screens attached (you cannot really click; judge from the screens what you would do). The checkpoints are
the steps the app should let you reach, in order. If the screens or the wording would stop you, say at
which checkpoint number you would get stuck and why. If you would finish, say so.

=== TASKS ===
{tasks}
=== END ===

{screens_line}
Rules:
- Be concrete about what you see on the screen. Do not assume features that are not on the screens.
- Stuck is a real answer. Do not guess your way past a step you would not understand.

Write the file {out} with your file-writing tool (do not just print it). The content must be ONLY this
JSON, no markdown fence, no other text:
{schema}
"""

PRICE_BLOCK = """
=== PRICE ===
The price is stated in the keynote. Answer four questions with a number in the same currency ({currency}):
- price_too_cheap: the price at which it seems too cheap to be any good
- price_bargain: the price at which it feels like a bargain
- price_expensive: the price at which it starts to feel expensive, but you might still buy
- price_too_expensive: the price above which you would not buy it at all
=== END ===
"""


class PanelError(Exception):
    pass


# ── files ───────────────────────────────────────────────────────────────────────
def load_json(path):
    if not os.path.exists(path):
        raise PanelError("missing: %s" % path)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def read_text(path):
    if not os.path.exists(path):
        raise PanelError("missing: %s" % path)
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


# ── inputs ──────────────────────────────────────────────────────────────────────
def load_inputs(d):
    """customer.json, product.md, features.json must be filled in (no TODO left)."""
    customer = load_json(os.path.join(d, "customer.json"))
    if not customer.get("roles"):
        raise PanelError("customer.json needs a 'roles' list (at least one role)")
    if len(customer.get("objections", [])) < 3:
        raise PanelError("customer.json needs at least 3 'objections'")
    for r in customer["roles"]:
        if not r.get("name") or len(r.get("age", [])) != 2:
            raise PanelError("every role needs a 'name' and an 'age' [low, high]")
        if r.get("decision_type") not in DECISION_TYPES:
            raise PanelError("role %r needs decision_type: buyer, user or influencer" % r.get("name"))
    product = read_text(os.path.join(d, "product.md"))
    features = load_json(os.path.join(d, "features.json")).get("features", [])
    if not features:
        raise PanelError("features.json needs at least one feature")
    for f in features:
        if not all(f.get(k) for k in ("id", "name", "what")):
            raise PanelError("every feature needs 'id', 'name' and 'what'")
        if not f.get("steps"):
            raise PanelError("feature %s needs 'steps' (the checkpoints for the task test)" % f["id"])
    blob = json.dumps(customer, ensure_ascii=False) + product + json.dumps(features, ensure_ascii=False)
    if "TODO" in blob:
        raise PanelError("launch/ still has template text (TODO): fill in customer.json, product.md, features.json")
    return customer, product, features


def price_enabled(product):
    return bool(PRICE_RE.search(product))


def feature_text(features):
    return "\n".join("- %s · %s: %s" % (f["id"], f["name"], f["what"]) for f in features)


def task_text(features):
    blocks = []
    for f in features:
        steps = "\n".join("   %d) %s" % (k, s) for k, s in enumerate(f["steps"], 1))
        blocks.append("- %s · %s\n  Goal: %s\n  Checkpoints, in order:\n%s" % (f["id"], f["name"], f["what"], steps))
    return "\n".join(blocks)


def screens_list(d):
    files = sorted(glob.glob(os.path.join(d, "screens", "*")))
    return [f for f in files if not os.path.basename(f).startswith(".")]


def screens_line(d):
    files = screens_list(d)
    if not files:
        return ""
    return ("Screenshots (open with Read and look at them):\n"
            + "\n".join("- " + os.path.abspath(f) for f in files) + "\n")


def render_schema(pid, lines):
    body = ",\n".join("  " + line for line in lines)
    return "{\n  \"id\": \"%s\",\n%s\n}" % (pid, body)


def schema_text(pid, dtype, rnd, features, price):
    """The exact JSON a persona must write, for its role and round."""
    lines = []
    if rnd == "2":
        lines += ['"changed_mind": true or false',
                  '"why_changed": "what changed and why; leave empty if nothing changed"']
    for key, _ in FIELDS[dtype][rnd]:
        lines.append('"%s": %s' % (key, DESCRIPTIONS[key]))
    if rnd == "1" and dtype == "buyer" and price:
        lines += ['"%s": a number' % k for k in PRICE_KEYS]
    reactions = ",\n".join(REACTION_SCHEMA.replace("__FID__", f["id"]) for f in features)
    lines.append('"feature_reactions": [\n%s\n  ]' % reactions)
    lines.append('"would_change_my_mind": "what would change your answer, or leave empty"')
    if rnd == "1":
        lines.append('"questions": ["up to 3 questions you would ask at the press conference, in your own voice"]')
    return render_schema(pid, lines)


# ── dealing ─────────────────────────────────────────────────────────────────────
def quota(items, n):
    """Split n across items by their share, exactly (largest remainder)."""
    total = sum(float(it.get("share", 1)) for it in items) or 1.0
    raw = [n * float(it.get("share", 1)) / total for it in items]
    counts = [int(x) for x in raw]
    order = sorted(range(len(items)), key=lambda i: raw[i] - counts[i], reverse=True)
    for i in order[: n - sum(counts)]:
        counts[i] += 1
    return counts


def deal(customer, n, seed):
    """Same customer + n + seed gives the same cards, every time."""
    rng = random.Random(seed)
    roles = []
    for r, k in zip(customer["roles"], quota(customer["roles"], n)):
        roles += [r] * k
    rng.shuffle(roles)
    names = NAMES[:]
    rng.shuffle(names)
    habits = customer.get("habits") or []
    cards = []
    for i, role in enumerate(roles):
        lo, hi = role["age"]
        inc = role.get("income")
        name = names[i % len(names)]
        if i >= len(names):
            name = "%s %d" % (name, i // len(names) + 1)
        cards.append({
            "id": "P%02d" % (i + 1),
            "name": name,
            "role": role["name"],
            "decision_type": role["decision_type"],
            "age": rng.randint(int(lo), int(hi)),
            "income": int(round(rng.uniform(float(inc[0]), float(inc[1])), -3)) if inc else None,
            "how": role.get("how", ""),
            "decision": role.get("decision", ""),
            "temper": TEMPERS[rng.randrange(len(TEMPERS))],
            "objection": customer["objections"][rng.randrange(len(customer["objections"]))],
            "habit": habits[rng.randrange(len(habits))] if habits else "",
        })
    return cards


def card_md(c, currency):
    inc = ("Income: about %s %s per year" % ("{:,}".format(c["income"]), currency)) if c["income"] else "Income: none (household budget)"
    return "\n".join([
        "# %s · %s (%d)" % (c["id"], c["name"], c["age"]),
        "",
        "- Role: %s (%s)" % (c["role"], c["decision_type"]),
        "- %s" % inc,
        "- How they decide: %s" % c["how"],
        "- Who decides: %s" % c["decision"],
        "- Personality: %s" % c["temper"],
        "- Daily context: %s" % (c["habit"] or "-"),
        "- First objection: \"%s\"" % c["objection"],
        "",
    ])


def cmd_init(d, n, seed, force):
    customer, _, _ = load_inputs(d)
    if n < len(customer["roles"]):
        raise PanelError("n=%d is less than the %d roles: each role needs at least one persona" % (n, len(customer["roles"])))
    ans = os.path.join(d, "answers")
    if os.path.isdir(ans) and any(os.scandir(ans)) and not force:
        raise PanelError("answers already exist; dealing again deletes them: pass --force")
    if force:
        for sub in ("answers", "briefs", "personas"):
            shutil.rmtree(os.path.join(d, sub), ignore_errors=True)
    if seed is None:
        seed = random.SystemRandom().randrange(1, 10 ** 6)
    cards = deal(customer, n, seed)
    write_json(os.path.join(d, "personas", "cards.json"), {"n": n, "seed": seed, "cards": cards})
    for c in cards:
        with open(os.path.join(d, "personas", c["id"] + ".md"), "w", encoding="utf-8") as fh:
            fh.write(card_md(c, customer.get("currency", "")))
    for sub in ("answers/r1", "answers/r2", "answers/task", "briefs"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    print("dealt %d personas (seed %s) into %s/personas/. Next: briefs --round 1" % (len(cards), seed, d))


def load_cards(d):
    data = load_json(os.path.join(d, "personas", "cards.json"))
    return data["cards"], data["seed"]


def answer_path(d, rnd, pid):
    return os.path.join(d, "answers", "r" + rnd if rnd != "task" else "task", pid + ".json")


def brief_path(d, rnd, pid):
    return os.path.join(d, "briefs", "r" + rnd if rnd != "task" else "task", pid + ".md")


def project_state(d):
    """(customer, product, features, cards, price) after validating the inputs."""
    customer, product, features = load_inputs(d)
    cards, _ = load_cards(d)
    return customer, product, features, cards, price_enabled(product)


def persona_price(card, price):
    """Price questions go to buyers only, and only when the product states a price."""
    return price and card["decision_type"] == "buyer"


# ── briefs ──────────────────────────────────────────────────────────────────────
def parse_answers_md(d):
    """qa/answers.md: the text under each '### Qn' heading is the team's answer."""
    path = os.path.join(d, "qa", "answers.md")
    if not os.path.exists(path):
        return {}
    out, cur = {}, None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^###\s+(Q\d+)\b", line)
            if m:
                cur = m.group(1)
                out[cur] = []
            elif line.startswith("## "):
                cur = None
            elif cur:
                out[cur].append(line.rstrip("\n"))
    return {k: "\n".join(v).strip() for k, v in out.items() if "\n".join(v).strip()}


def build_brief(d, rnd, c, features, product, currency, qa_text="", prev_text=""):
    pid = c["id"]
    out = os.path.abspath(answer_path(d, rnd, pid))
    price = persona_price(c, price_enabled(product))
    common = dict(name=c["name"], age=c["age"], role=c["role"], how=c["how"], decision=c["decision"],
                  temper=c["temper"], objection=c["objection"], out=out, screens_line=screens_line(d),
                  role_help=ROLE_HELP[c["decision_type"]], product=product, features=feature_text(features))
    if rnd == "1":
        return BRIEF_R1.format(
            income_line=("Your yearly income is about %s %s.\n" % ("{:,}".format(c["income"]), currency)) if c["income"] else "",
            habit_line=("Your day: %s.\n" % c["habit"]) if c["habit"] else "",
            price_block=PRICE_BLOCK.format(currency=currency) if price else "",
            schema=schema_text(pid, c["decision_type"], "1", features, price), **common)
    if rnd == "2":
        return BRIEF_R2.format(
            prev=prev_text, qa=qa_text, schema=schema_text(pid, c["decision_type"], "2", features, False), **common)
    return BRIEF_TASK.format(
        tasks=task_text(features), schema=TASK_SCHEMA.replace("__ID__", pid), name=c["name"], age=c["age"],
        role=c["role"], how=c["how"], temper=c["temper"], out=out, screens_line=screens_line(d))


def cmd_briefs(d, rnd, wave):
    customer, product, features, cards, price = project_state(d)
    currency = customer.get("currency", "")
    if rnd == "task" and not screens_list(d):
        raise PanelError("the task test needs screenshots in %s/screens/: without them personas cannot judge "
                         "the flow and every answer is meaningless. Add screens, then re-run" % d)
    if price and not currency:
        raise PanelError("customer.json needs 'currency' (e.g. \"TL\") when product.md states a price")
    qa_text = ""
    if rnd == "2":
        answered = parse_answers_md(d)
        if not answered:
            raise PanelError("no answered questions in qa/answers.md: write your answers first")
        questions = {q["id"]: q["text"] for q in load_json(os.path.join(d, "qa", "questions.json"))}
        qa_text = "\n".join("Q (%s): %s\nA: %s\n" % (q, questions.get(q, ""), a)
                            for q, a in answered.items() if q in questions)
        if not qa_text.strip():
            raise PanelError("qa/answers.md answers match no question in qa/questions.json")
    todo, skipped = [], []
    for c in cards:
        pid = c["id"]
        if answer_problem_file(answer_path(d, rnd, pid), c, features, rnd, persona_price(c, price)) is None:
            continue  # already has a valid answer for this round
        prev_text = ""
        if rnd == "2":
            prev = answer_path(d, "1", pid)
            if answer_problem_file(prev, c, features, "1", persona_price(c, price)) is not None:
                skipped.append(pid)
                continue
            with open(prev, encoding="utf-8") as fh:
                prev_text = json.dumps(json.load(fh), ensure_ascii=False, indent=1)
        bp = brief_path(d, rnd, pid)
        os.makedirs(os.path.dirname(bp), exist_ok=True)
        with open(bp, "w", encoding="utf-8") as fh:
            fh.write(build_brief(d, rnd, c, features, product, currency, qa_text, prev_text))
        todo.append((pid, os.path.abspath(bp)))
    if not todo:
        print("every persona has a valid round %s answer" % rnd)
        return
    waves = [todo[i:i + wave] for i in range(0, len(todo), wave)]
    print("%d briefs in %d waves of up to %d. Launch one wave at a time, all calls in one message:" % (
        len(todo), len(waves), wave))
    for k, w in enumerate(waves, 1):
        print("wave %d: %s" % (k, " ".join("%s=%s" % job for job in w)))
    if skipped:
        print("round 1 answer missing or invalid, skipped: %s (run check --round 1 first)" % ", ".join(skipped))


# ── answers ─────────────────────────────────────────────────────────────────────
def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _reactions_problem(fr, features):
    if not isinstance(fr, list):
        return "'feature_reactions' must be a list"
    ids = {f["id"] for f in features}
    seen = set()
    for f in fr:
        if not isinstance(f, dict) or f.get("feature") not in ids:
            return "unknown feature: %r" % (f.get("feature") if isinstance(f, dict) else f)
        if f["feature"] in seen:
            return "%s is reacted to twice" % f["feature"]
        if not isinstance(f.get("understood"), bool):
            return "%s: 'understood' must be true or false" % f["feature"]
        for k in ("value", "complexity"):
            if not _is_int(f.get(k)) or not 1 <= f[k] <= 5:
                return "%s: '%s' must be an integer 1-5" % (f["feature"], k)
        if not str(f.get("comment", "")).strip():
            return "%s: 'comment' is empty" % f["feature"]
        if not isinstance(f.get("missing", ""), str):
            return "%s: 'missing' must be a string" % f["feature"]
        seen.add(f["feature"])
    if ids - seen:
        return "no reaction to features: %s" % ", ".join(sorted(ids - seen))
    return None


def _tasks_problem(tasks, features):
    if not isinstance(tasks, list):
        return "'tasks' must be a list"
    by_id = {f["id"]: f for f in features}
    seen = set()
    for t in tasks:
        if not isinstance(t, dict) or t.get("feature") not in by_id:
            return "unknown feature in tasks: %r" % (t.get("feature") if isinstance(t, dict) else t)
        fid = t["feature"]
        if fid in seen:
            return "%s is in tasks twice" % fid
        seen.add(fid)
        if not isinstance(t.get("completed"), bool):
            return "%s: 'completed' must be true or false" % fid
        if t["completed"]:
            if t.get("stuck_step") is not None:
                return "%s: completed but stuck_step is set" % fid
        else:
            n = len(by_id[fid]["steps"])
            if not _is_int(t.get("stuck_step")) or not 1 <= t["stuck_step"] <= n:
                return "%s: stuck_step must be a checkpoint number 1-%d" % (fid, n)
            if not str(t.get("why", "")).strip():
                return "%s: 'why' is empty for a stuck task" % fid
    if set(by_id) - seen:
        return "no task result for: %s" % ", ".join(sorted(set(by_id) - seen))
    return None


def _field_problem(a, key, kind):
    v = a.get(key)
    if kind == "bool":
        return None if isinstance(v, bool) else "'%s' must be true or false" % key
    if kind == "scale":
        return None if _is_int(v) and 1 <= v <= 5 else "'%s' must be an integer 1-5" % key
    if kind == "reason":
        return None if v in REASONS else "reason_code %r is not valid" % v
    return None if isinstance(v, str) and v.strip() else "'%s' is empty" % key


def decision_problem(a, dtype, rnd, price):
    """Checks the role-specific part of a round 1 or round 2 answer."""
    for key, kind in FIELDS[dtype][rnd]:
        p = _field_problem(a, key, kind)
        if p:
            return p
    if rnd == "2":
        if not isinstance(a.get("changed_mind"), bool):
            return "'changed_mind' must be true or false"
        if a.get("changed_mind") and not str(a.get("why_changed", "")).strip():
            return "changed_mind is true but 'why_changed' is empty"
    if rnd == "1" and dtype == "buyer" and price:
        for k in PRICE_KEYS:
            if not _is_num(a.get(k)) or a[k] <= 0:
                return "'%s' must be a positive number" % k
    return None


def answer_problem(a, pid, features, rnd, dtype, price=False):
    if not isinstance(a, dict):
        return "JSON is not an object"
    if a.get("id") != pid:
        return "id is %r, expected %s" % (a.get("id"), pid)
    if rnd == "task":
        return _tasks_problem(a.get("tasks"), features)
    p = decision_problem(a, dtype, rnd, price)
    if p:
        return p
    p = _reactions_problem(a.get("feature_reactions"), features)
    if p:
        return p
    if rnd == "1":
        q = a.get("questions")
        if not isinstance(q, list) or len(q) > 3 or not all(isinstance(x, str) and x.strip() for x in q):
            return "'questions' must be a list of at most 3 non-empty strings"
    return None


def answer_problem_file(path, card, features, rnd, price=False):
    if not os.path.exists(path):
        return "missing"
    try:
        with open(path, encoding="utf-8") as fh:
            a = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "not valid JSON"
    return answer_problem(a, card["id"], features, rnd, card["decision_type"], price)


def load_round(d, rnd):
    """Valid answers for a round, merged with their persona card. Returns (rows, skipped)."""
    _, _, features, cards, price = project_state(d)
    rows, skipped = [], []
    for c in cards:
        path = answer_path(d, rnd, c["id"])
        p = answer_problem_file(path, c, features, rnd, persona_price(c, price))
        if p:
            skipped.append((c["id"], p))
            continue
        with open(path, encoding="utf-8") as fh:
            a = json.load(fh)
        rows.append(dict(c, **a))
    return rows, skipped


def cmd_check(d, rnd):
    _, _, features, cards, price = project_state(d)
    probs = []
    for c in cards:
        p = answer_problem_file(answer_path(d, rnd, c["id"]), c, features, rnd, persona_price(c, price))
        if p:
            probs.append((c["id"], p))
    if not probs:
        print("round %s: all answers present and valid" % rnd)
        return 0
    for pid, p in probs:
        print("%s: %s" % (pid, p))
    print("%d missing or invalid. Re-run: briefs --round %s" % (len(probs), rnd))
    return 1


def cmd_save(d, rnd, pid, text):
    """File a persona's OWN reply that it printed instead of writing. Never used to answer for a persona."""
    _, _, features, cards, price = project_state(d)
    card = next((c for c in cards if c["id"] == pid), None)
    if card is None:
        raise PanelError("no persona %s on this panel" % pid)
    start = text.find("{")
    if start < 0:
        raise PanelError("no JSON in the reply")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise PanelError("the reply's JSON does not parse: %s" % e)
    p = answer_problem(obj, pid, features, rnd, card["decision_type"], persona_price(card, price))
    if p:
        raise PanelError("%s's answer is not valid (%s); re-run its brief instead" % (pid, p))
    path = answer_path(d, rnd, pid)
    write_json(path, obj)
    return path


def cmd_status(d):
    _, _, features, cards, price = project_state(d)
    print("%d personas (seed %s), price questions: %s" % (
        len(cards), load_cards(d)[1], "on for buyers" if price else "off (no price in product.md)"))
    for rnd in ROUNDS:
        ok = sum(1 for c in cards if answer_problem_file(
            answer_path(d, rnd, c["id"]), c, features, rnd, persona_price(c, price)) is None)
        print("round %s: %d/%d valid answers" % (rnd, ok, len(cards)))


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", default="launch", help="project folder (default: launch)")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", parents=[common])
    i.add_argument("--n", type=int, default=None, help="number of personas (default 100)")
    i.add_argument("--quick", action="store_true", help="20 personas, for a first look")
    i.add_argument("--seed", type=int, default=7)
    i.add_argument("--force", action="store_true")
    b = sub.add_parser("briefs", parents=[common])
    b.add_argument("--round", choices=ROUNDS, required=True)
    b.add_argument("--wave", type=int, default=10)
    c = sub.add_parser("check", parents=[common])
    c.add_argument("--round", choices=ROUNDS, required=True)
    s = sub.add_parser("save", parents=[common])
    s.add_argument("--round", choices=ROUNDS, required=True)
    s.add_argument("id")
    sub.add_parser("status", parents=[common])
    a = ap.parse_args(argv)
    try:
        if a.cmd == "init":
            n = a.n if a.n is not None else (QUICK_N if a.quick else DEFAULT_N)
            if n < 1:
                raise PanelError("--n must be at least 1")
            cmd_init(a.dir, n, a.seed, a.force)
        elif a.cmd == "briefs":
            cmd_briefs(a.dir, a.round, a.wave)
        elif a.cmd == "check":
            return cmd_check(a.dir, a.round)
        elif a.cmd == "save":
            print("saved %s" % cmd_save(a.dir, a.round, a.id, sys.stdin.read()))
        elif a.cmd == "status":
            cmd_status(a.dir)
    except PanelError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
