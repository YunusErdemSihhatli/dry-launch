---
name: dry-launch
description: >-
  Pre-launch dry run. Presents the app to simulated target users in a press-conference
  format. Each persona hears the keynote, rates every feature, answers the questions for
  its role (buyer, user or influencer), and asks questions. The user answers the questions,
  personas re-decide in round 2, and a task test shows where they get stuck on screens.
  Use when the user says "dry launch", "press conference", "test my launch", "what would
  personas think", "test the keynote", or "collect feature feedback".
argument-hint: "[init | keynote | pressroom | round2 | task | results] [--n 5]"
---

# dry-launch

Present a launch to target users before it ships, without spending money. Personas hear the keynote,
rate each feature, answer the questions for their role, and ask questions. The user answers, personas
re-decide, and a task test shows where the flow breaks on the screens.

## Tools

All bookkeeping goes through the scripts in this folder. Standard library only, no network.
`panel.py` deals personas, writes briefs, and checks answers. `pricing.py` computes the Van Westendorp
range. `tally.py` prepares the clustering inputs and writes the report.

```bash
DL="$HOME/.claude/skills/dry-launch"
python3 "$DL/panel.py" <init|briefs|check|save|status> --dir launch ...
python3 "$DL/tally.py" <cluster prepare|cluster apply|results> --dir launch ...
```

The project folder is `launch/`, inside the product repo being launched (not inside the dry-launch repo).
Create it from the example, which is in the dry-launch repo:

```bash
REPO="$(dirname "$(readlink -f "$DL")")"
cp -R "$REPO/launch.example" launch && mkdir -p launch/qa launch/screens
```

```
launch/
  customer.json    audience: roles, each with a decision_type, and the currency
  product.md       keynote text; if it states a price, buyers get the price questions
  features.json    each feature: id, name, what, steps (the steps are the task checkpoints)
  screens/         screenshots of the app (required for the task test)
  personas/        generated cards (cards.json + P01.md ...)
  briefs/          one brief per persona and round
  answers/         r1/ r2/ task/ : each persona's answer (JSON, written by the subagent)
  qa/              raw and clustered questions and themes, and your answers.md
  report.md        the report
```

## Step 0: inputs

`customer.json`, `product.md`, `features.json` must be filled in. The scripts stop on any `TODO`, on a
feature with no `steps`, and on a role without `decision_type`. Each role has one of:

- `buyer`: pays for it. Answers buys, reason, and the four price questions when the product states a price.
- `user`: uses it but does not pay. Answers wants_it (1-5), would_ask_parent, would_keep_using_after_week.
- `influencer`: is asked by buyers. Answers would_recommend (1-5) and concerns.

Every role rates every feature. The purchase rate and the price range come from buyers only. Set
`currency` (for example "TL") in `customer.json`; the script requires it when the product states a price.

The user writes their own product. You may help draft the template, but do not invent their product.
Show a short summary (roles and their types, features, whether a price is stated) and ask for corrections
first. The wrong audience makes the whole panel wrong.

## Step 1: init (persona cards)

```bash
python3 "$DL/panel.py" init --dir launch --n 5 --seed 7
```

The same customer, n, and seed always give the same cards. Cards are readable at `launch/personas/P01.md`.
Use `--n 30` for a fuller panel. With a few roles, n must be at least the number of roles so each role
appears.

## Step 2: keynote (round 1)

```bash
python3 "$DL/panel.py" briefs --dir launch --round 1
```

The script writes one brief per persona and lists them in waves of 10. For each wave, send **one message
with one Agent call per persona in that wave**:

- `subagent_type`: `general-purpose`
- `model`: `haiku`
- `description`: `keynote P01`
- `prompt`: `Read <brief path> and follow it exactly. It is your whole brief.`

Do not start the next wave before the current one finishes. Then:

```bash
python3 "$DL/panel.py" check --dir launch --round 1
```

Re-run `briefs --round 1` for anything missing or invalid and dispatch only those. If a subagent prints its
JSON instead of writing the file, file it with `python3 "$DL/panel.py" save --dir launch --round 1 P07 < reply.txt`.
Never write a brief or a persona's answer yourself.

## Step 3: pressroom (questions and themes)

Two kinds of free text are clustered by meaning, which is a judgement call, so a Sonnet subagent does it.
The script prepares the inputs and checks the result:

```bash
python3 "$DL/tally.py" cluster prepare --dir launch --what questions
python3 "$DL/tally.py" cluster prepare --dir launch --what themes
```

- `questions`: the questions personas asked at the press conference.
- `themes`: buyer reasons, buyer objections, and influencer concerns.

Dispatch **one** Sonnet subagent (`subagent_type: general-purpose`, `model: sonnet`) with this prompt, using
absolute paths:

> Read `<launch>/qa/questions_raw.json` and `<launch>/qa/themes_raw.json`. Each item has a `ref`, a `persona`,
> a `kind`, and a `text`. For each file, group the items that mean the same thing (different wording, same
> concern). Write `<launch>/qa/questions_clusters.json` and `<launch>/qa/themes_clusters.json`, each a JSON
> list in the form `[{"text": "the clearest wording", "members": ["P03-1", "P07-reason"]}]`. Every ref in the
> input must appear in exactly one cluster. Do not invent items and do not drop any. Write the files with
> your file-writing tool and print nothing else except the cluster counts.

Then apply both:

```bash
python3 "$DL/tally.py" cluster apply --dir launch --what questions --top 10
python3 "$DL/tally.py" cluster apply --dir launch --what themes
```

`apply` refuses a cluster file that misses an item, uses an unknown ref, or puts an item in two clusters.
It writes `launch/qa/questions.md` (the top 10 by count) and an empty `launch/qa/answers.md`.

Stop here and tell the user: "Fill in launch/qa/answers.md and tell me when you are done." Do not start round 2
until they answer, or until you have been asked to answer them yourself. Unanswered questions do not go to
round 2.

## Step 4: round 2

```bash
python3 "$DL/panel.py" briefs --dir launch --round 2
```

Each persona reads its own round-1 answer and the team's answers, then re-decides. Dispatch in the same wave
pattern as step 2, then `check --round 2`. Only personas with a valid round-1 answer get a round-2 brief.

## Step 5: task test

Each persona gets the goal of each feature, with its checkpoints from `features.json`, and the screens. It
records the checkpoint where it would get stuck and why. It does not depend on the Q&A, so it can run any
time after step 1.

The script **refuses to run this round without screenshots** in `launch/screens/`. Without them every persona
reports being stuck at the first checkpoint, which is meaningless.

```bash
python3 "$DL/panel.py" briefs --dir launch --round task
```

Dispatch as in step 2, then `check --round task`. Be clear with the user about the limit: the persona sees
screenshots and text, so this tests the wording and the visible flow, not the running app.

## Step 6: results

```bash
python3 "$DL/tally.py" results --dir launch
```

This writes `launch/report.md`. Give the user the report, with these sections in mind:

1. Buy rate for buyers, by round. Then the by-role table, where users and influencers show their own metrics.
2. The feature table. Each recommendation (keep / improve / drop) is derived from the scores, and the report
   states the thresholds. Include anything people said is missing.
3. The three weakest features, one quote each.
4. Why buyers pass and why they buy.
5. Themes in free-text answers, clustered.
6. Round 2: how many changed their mind, and what convinced them.
7. Task test: which checkpoints people got stuck on.
8. Price range, if the product states a price (buyers only).
9. Warnings: simulated personas, the buy rate is an upper bound, and the three riskiest assumptions to verify
   with real users.

Do not present persona quotes as real customer testimonials. The recommendations are suggestions; the
decision is the user's.

## Rules

- Personas do not see each other. A brief never contains another persona's answer.
- Never write answers yourself. Missing or invalid answers are dispatched again.
- Do not start round 2 until the questions are answered.
- Run the task test only with screenshots present.
- Before dispatching more than 30 subagents, tell the user the count and suggest accept-edits mode
  (Shift+Tab) so each file write is not approved one by one.
