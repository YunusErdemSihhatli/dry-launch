# dry-launch

A Claude Code skill for a **dry launch**: present your app to simulated target users in a press-conference
format before you ship. Each persona hears the keynote, rates every feature, answers the questions for its role
(buyer, user, or influencer), and asks questions. You answer the questions, personas re-decide, a task test
checks the screens, and you get a report with the risks to verify.

It is for finding objections and weak spots early. It does not predict real sales.

## How it works

1. **init**: deal persona cards from your target audience. Each role has a `decision_type`: `buyer`, `user`,
   or `influencer`. The same seed always gives the same cards.
2. **keynote (round 1)**: each persona reads the keynote and rates every feature (understood, value,
   complexity, comment, what is missing). Then it answers its role's questions and asks up to three questions.
   Buyers also give four price answers if the product states a price.
3. **pressroom**: a Sonnet subagent clusters the questions and the free-text themes by meaning. You get the top
   10 questions and answer them.
4. **round 2**: each persona re-decides with your answers in hand.
5. **task test**: each persona walks the goal of each feature, checkpoint by checkpoint, on your screenshots, and
   reports where it would get stuck and why.
6. **results**: `report.md` with buy rate for buyers, the by-role table, feature recommendations derived from the
   scores, reasons, themes, task failures, the price range (buyers only), and a warnings section.

Every persona's answer is written by a subagent to its own file. The scripts never answer for a persona; they
deal cards, write briefs, check answers, and tally them.

## Install

```bash
git clone <this repo> ~/projects/dry-launch
ln -s ~/projects/dry-launch/skill ~/.claude/skills/dry-launch
```

Standard library Python 3 only. No network, no API keys.

## Start a launch (in your product repo)

The `launch/` folder is created **inside the product repo you are launching**, not in this repo. From the product repo:

```bash
cp -R ~/projects/dry-launch/launch.example launch && mkdir -p launch/qa launch/screens
```

Then edit `launch/customer.json`, `launch/product.md`, and `launch/features.json`, and put screenshots of the app
into `launch/screens/`. Ask Claude Code to "run dry-launch". The skill walks through the steps and dispatches the
subagents. Keep `launch/` out of your product's commits, for example by adding it to that repo's `.gitignore`.

`launch.example/` is a small working example: a coding toy with a stated price, three roles (buyer, user,
influencer), two features, and four mockup screens.

## Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

The tests cover persona dealing, role-specific schemas and validation, brief content (no leaking of other
personas' answers), the task test's screenshot requirement, the clustering handoff, the report sections, and the
price range.

## Layout

```
skill/
  SKILL.md        the instructions Claude Code follows
  panel.py        deal personas, write briefs, check and save answers
  pricing.py      Van Westendorp price range (adapted from founder-skill, MIT)
  tally.py        clustering inputs, clustered results, the report
launch.example/   a sample project, including mockup screens
tests/            unit tests (unittest)
```

## Limits

- Personas are language-model simulations. They lean agreeable, so treat the buy rate as an upper bound.
- The task test sees screenshots and text, not the running app. Mockups test the wording and the visible flow.
- Confirm the big calls with real users: a waitlist, a pre-sale, or a landing page with a price.

## License

MIT. See [LICENSE](LICENSE). The price logic is adapted from founder-skill by Jake Schincariol (MIT).
