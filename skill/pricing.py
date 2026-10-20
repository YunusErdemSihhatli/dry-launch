"""Van Westendorp price sensitivity for dry-launch. Standard library only.

Adapted from founder-skill's founder-pricing/van_westendorp.py (MIT, Copyright (c) 2026
Jake Schincariol). Same four points and the same crossing logic, reading the dry-launch
answer fields instead of a CSV or the founder-consumer answers folder.

Each persona gives four prices: too cheap, bargain, expensive, too expensive.
    PMC  point of marginal cheapness   below this, too many think it is too cheap
    PME  point of marginal expensiveness above this, too many think it is too expensive
    OPP  optimal price point            as many say "too cheap" as "too expensive"
    IPP  indifference price point       as many say "a bargain" as "expensive"
PMC to PME is the acceptable range. Simulated answers: use the range to choose what to test.
"""

MIN_ANSWERS = 5


def usable(rows, keys):
    """Keep rows with four positive numbers in order (too cheap <= bargain <= expensive <= too expensive).

    Returns (tuples, dropped_count).
    """
    out, dropped = [], 0
    for r in rows:
        vals = [r.get(k) for k in keys]
        ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in vals)
        if ok and vals[0] <= vals[1] <= vals[2] <= vals[3]:
            out.append(tuple(float(v) for v in vals))
        else:
            dropped += 1
    return out, dropped


def curves(rows, grid):
    n = float(len(rows))
    tc = [sum(1 for r in rows if r[0] >= p) / n for p in grid]   # too cheap at p (falls)
    ch = [sum(1 for r in rows if r[1] >= p) / n for p in grid]   # a bargain at p (falls)
    ex = [sum(1 for r in rows if r[2] <= p) / n for p in grid]   # expensive at p (rises)
    te = [sum(1 for r in rows if r[3] <= p) / n for p in grid]   # too expensive at p (rises)
    return tc, ch, ex, te


def cross(grid, falling, rising):
    """First price where the rising curve meets the falling one (linear interpolation)."""
    for i in range(1, len(grid)):
        d0 = rising[i - 1] - falling[i - 1]
        d1 = rising[i] - falling[i]
        if d0 <= 0 <= d1 and d1 != d0:
            t = -d0 / (d1 - d0)
            return grid[i - 1] + t * (grid[i] - grid[i - 1])
        if d0 == 0:
            return grid[i - 1]
    return None


def analyse(rows, steps=400):
    """rows: tuples of four floats. Returns a dict, or None if there are too few answers."""
    if len(rows) < MIN_ANSWERS:
        return None
    lo = min(r[0] for r in rows)
    hi = max(r[3] for r in rows)
    step = max(0.01, round((hi - lo) / steps, 2)) if hi > lo else 0.01
    grid, p = [], lo
    while p <= hi + 1e-9:
        grid.append(round(p, 4))
        p += step
    tc, ch, ex, te = curves(rows, grid)
    not_cheap = [1 - v for v in ch]
    not_exp = [1 - v for v in ex]
    points = {
        "PMC": cross(grid, tc, not_cheap),
        "PME": cross(grid, not_exp, te),
        "OPP": cross(grid, tc, te),
        "IPP": cross(grid, ch, ex),
    }
    return {"n": len(rows), "points": points, "range": (points["PMC"], points["PME"])}


def from_answers(answer_rows, keys):
    """Run the analysis on answer dicts. Returns (result or None, dropped)."""
    tuples, dropped = usable(answer_rows, keys)
    return analyse(tuples), dropped


def fmt(v):
    return "n/a" if v is None else "%.2f" % v


def report_lines(result, dropped, currency=""):
    """Markdown lines for the report."""
    if result is None:
        return ["Not enough complete price answers for a range yet (need at least %d)." % MIN_ANSWERS]
    p = result["points"]
    c = (" " + currency) if currency else ""
    L = ["| point | price | meaning |", "| --- | ---: | --- |",
         "| PMC | %s%s | below this, too many think it is too cheap to be good |" % (fmt(p["PMC"]), c),
         "| OPP | %s%s | as many say too cheap as too expensive |" % (fmt(p["OPP"]), c),
         "| IPP | %s%s | as many call it a bargain as call it expensive |" % (fmt(p["IPP"]), c),
         "| PME | %s%s | above this, too many say it is too expensive to buy |" % (fmt(p["PME"]), c),
         "",
         "**Acceptable range: %s%s to %s%s** (from %d complete answers%s)." % (
             fmt(p["PMC"]), c, fmt(p["PME"]), c, result["n"],
             ", %d dropped as incomplete or out of order" % dropped if dropped else "")]
    return L
