"""Read what's working from the wells-dashboard repo.

Pulls the plan's evidence-backed moves and computes, from the newest snapshot,
median plays by reel length and by topic tag. Every number comes straight from
the snapshot so it can be checked.
"""
import glob
import json
import os
from statistics import median

DEFAULT_DASH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "wells-dashboard")

BUCKETS = [(0, 15, "15 s or less"), (15, 40, "16-40 s"), (40, 60, "41-60 s"), (60, 10**6, "over 60 s")]


def read(dash=DEFAULT_DASH):
    if not os.path.isdir(dash):
        return {"error": f"dashboard repo not found at {dash}"}
    snaps = sorted(glob.glob(os.path.join(dash, "history", "*.json")))
    if not snaps:
        return {"error": "no snapshots in history/"}
    with open(snaps[-1]) as f:
        snap = json.load(f)
    tags = {}
    tags_path = os.path.join(dash, "tags.json")
    if os.path.exists(tags_path):
        with open(tags_path) as f:
            t = json.load(f)
        tags = {k: t["labels"].get(v, v) for k, v in t.get("reels", {}).items()}
    reels = [r for r in snap.get("instagram", {}).get("reels", []) if r.get("plays") is not None]

    by_len = []
    for lo, hi, label in BUCKETS:
        p = [r["plays"] for r in reels if r.get("sec") is not None and lo < r["sec"] <= hi]
        if p:
            by_len.append({"length": label, "reels": len(p), "median_plays": median(p)})

    by_tag = {}
    for r in reels:
        by_tag.setdefault(tags.get(r["id"], "Untagged"), []).append(r["plays"])
    by_tag = sorted(({"topic": k, "reels": len(v), "median_plays": median(v)} for k, v in by_tag.items()),
                    key=lambda x: -x["median_plays"])

    moves = []
    plan_path = os.path.join(dash, "plan.json")
    if os.path.exists(plan_path):
        with open(plan_path) as f:
            plan = json.load(f)
        moves = [{"title": m["title"], "evidence": m["evidence"], "action": m["action"]}
                 for m in plan.get("moves", [])]

    best = max(by_len, key=lambda b: b["median_plays"]) if by_len else None
    return {
        "snapshot": os.path.basename(snaps[-1]),
        "reels_counted": len(reels),
        "by_length": by_len,
        "by_topic": by_tag,
        "best_length": best["length"] if best else None,
        "plan_moves": moves,
    }


def captions(dash=DEFAULT_DASH, top=8):
    """What Wells's best reels said: top captions by plays, and how many used hashtags."""
    snaps = sorted(glob.glob(os.path.join(dash, "history", "*.json")))
    if not snaps:
        return {"error": "no snapshots in history/"}
    with open(snaps[-1]) as f:
        snap = json.load(f)
    reels = [r for r in snap.get("instagram", {}).get("reels", []) if r.get("plays") is not None]
    best = sorted(reels, key=lambda r: -r["plays"])[:top]
    words = [len(r.get("cap", "").split()) for r in reels if r.get("cap") and r["cap"] != "(no caption)"]
    return {
        "snapshot": os.path.basename(snaps[-1]),
        "top": [{"plays": r["plays"], "sec": r.get("sec"), "cap": r.get("cap", "")} for r in best],
        "with_hashtags": sum("#" in r.get("cap", "") for r in reels),
        "reels_counted": len(reels),
        "median_caption_words": median(words) if words else None,
    }


if __name__ == "__main__":
    print(json.dumps(read(), indent=1))
