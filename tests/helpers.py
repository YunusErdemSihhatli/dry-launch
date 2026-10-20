"""Shared test helpers: copy the example project into a temp dir and build valid answers."""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skill"))
EXAMPLE = os.path.join(ROOT, "launch.example")


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def make_project():
    """Returns (tmp_root, launch_dir). Call shutil.rmtree(tmp_root) when done."""
    tmp = tempfile.mkdtemp(prefix="dry-launch-test-")
    dst = os.path.join(tmp, "launch")
    shutil.copytree(EXAMPLE, dst)
    return tmp, dst


def feature_reactions(features, value=4, complexity=2, missing=""):
    return [
        {"feature": f["id"], "understood": True, "value": value, "complexity": complexity,
         "comment": "comment on %s" % f["id"], "missing": missing}
        for f in features
    ]


def r1_answer(pid, features, dtype="buyer", buys=True, price=True):
    a = {"id": pid, "feature_reactions": feature_reactions(features, value=4 if buys else 2),
         "would_change_my_mind": "a cheaper price", "questions": ["How long does the battery last?"]}
    if dtype == "buyer":
        a.update(buys=buys, reason_code="need" if buys else "price",
                 reason="because I want it" if buys else "too expensive for now",
                 top_objection="battery life")
        if price:
            a.update(price_too_cheap=500, price_bargain=900, price_expensive=1700, price_too_expensive=2400)
    elif dtype == "user":
        a.update(wants_it=4 if buys else 2, would_ask_parent=buys, would_keep_using_after_week=buys)
    else:
        a.update(would_recommend=4 if buys else 2, concerns="it might add to screen time")
    return a


def r2_answer(pid, features, dtype="buyer", changed=False):
    a = {"id": pid, "changed_mind": changed, "why_changed": "the battery answer convinced me" if changed else "",
         "feature_reactions": feature_reactions(features), "would_change_my_mind": ""}
    if dtype == "buyer":
        a.update(buys=True, reason_code="need", reason="round two reason")
    elif dtype == "user":
        a.update(wants_it=4, would_ask_parent=True, would_keep_using_after_week=True)
    else:
        a.update(would_recommend=4, concerns="still a bit worried about screen time")
    return a


def task_answer(pid, features, stuck=False):
    tasks = []
    for f in features:
        if stuck:
            tasks.append({"feature": f["id"], "completed": False, "stuck_step": 1, "why": "unclear button"})
        else:
            tasks.append({"feature": f["id"], "completed": True, "stuck_step": None, "why": ""})
    return {"id": pid, "tasks": tasks, "overall": "fine"}
