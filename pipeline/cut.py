"""Stage 1: the cutter.

    python3 -m pipeline.cut --job <job_id>            # find moments + build cut lists
    python3 -m pipeline.cut --job <job_id> --report   # just reprint the report

Splits each clip into sentences and loud moments ("candidates"), drops
silence, leading filler words and retakes, scores each moment, picks a hook
and builds a cut list per platform from targets.json. The cutter agent then
reviews the report and can edit job.json "cuts" by hand before rendering.
"""
import argparse
import difflib
import json
import os
import re

from . import job as J
from . import media
from .transcribe import FILLERS, norm, sentences

HERE = os.path.dirname(os.path.abspath(__file__))

PROBLEM = {"leak", "leaking", "leaked", "broke", "broken", "blew", "blown", "seized", "stuck", "cracked",
           "melted", "smoke", "smoking", "noise", "won't", "wont", "dead", "failed", "problem", "issue",
           "everywhere", "burnt", "burned", "worn", "destroyed", "shot", "toast", "missing", "slipping",
           "grinding", "knocking", "overheating", "upside", "nest", "mouse", "rust", "rusted", "snapped"}
REVEAL = {"look", "found", "inside", "actually", "finally", "fixed", "runs", "running", "started",
          "fired", "check", "turns", "culprit", "reason", "guess", "never", "crazy", "wild"}
LEAD_IN = {"okay", "ok", "so", "alright", "and", "well", "yeah", "'cause", "cause", "like", "but"}
RETAKE_CUES = [r"let me (say|do|try) (that|this|it) again", r"start (that )?over", r"one more time",
               r"take (two|2)", r"scratch that", r"hold on", r"wait,? (no|actually)", r"redo"]


def _snap_window(db, t, before, after):
    if len(db) == 0:
        return t
    lo = max(0, int((t - before) / media.HOP))
    hi = min(len(db), int((t + after) / media.HOP) + 1)
    if lo >= hi:
        return t
    seg = db[lo:hi]
    j = lo + int(seg.argmin())
    return round(j * media.HOP, 2)


def _score(text_words, dur, loud_overlap):
    toks = [norm(w) for w in text_words]
    p = sum(t in PROBLEM for t in toks)
    r = sum(t in REVEAL for t in toks)
    fill = sum(t in FILLERS for t in toks)
    s = 1 + 2 * p + 1.5 * r + 1.5 * loud_overlap - 0.5 * fill
    if any(w.endswith("!") for w in text_words):
        s += 0.5
    if dur > 12:
        s -= (dur - 12) * 0.2
    return round(s, 2), p, r


def _overlap(a0, a1, regions):
    return sum(max(0, min(a1, e) - max(a0, s)) for s, e in regions)


def strip_lead_in(words):
    """Drop filler words and soft lead-ins ("Um,", "Okay, so", "you know") at the start."""
    k = 0
    while k < len(words) - 2:
        w = norm(words[k]["w"])
        if w in LEAD_IN | FILLERS:
            k += 1
        elif w == "you" and norm(words[k + 1]["w"]) == "know":
            k += 2
        else:
            break
    return words[k:], " ".join(w["w"] for w in words[:k])


def clauses(words):
    """Split a sentence at commas."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if w["w"].endswith(","):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [c for c in out if len(c) >= 3]


def _piece(clip, words, db, lo, hi, loud, kind="speech"):
    s = max(lo, _snap_window(db, max(0, words[0]["s"] - 0.12), 0.3, 0.05))
    e = min(hi, _snap_window(db, min(clip["duration"], words[-1]["e"] + 0.15), 0.05, 0.3))
    if e - s < 0.3:
        return None
    text = " ".join(w["w"] for w in words).rstrip(",")
    sc, p, r = _score([w["w"] for w in words], e - s, min(1.0, _overlap(s, e, loud)))
    return {"src": clip["id"], "start": round(s, 2), "end": round(e, 2), "dur": round(e - s, 2),
            "kind": kind, "text": text, "score": sc, "problem": p, "reveal": r,
            "fillers": sum(norm(w["w"]) in FILLERS for w in words),
            "approx": any(w.get("approx") for w in words), "flags": []}


def find_candidates(jb, db_cache=None):
    cands = []
    for clip in jb["sources"]:
        db = db_cache.get(clip["id"]) if db_cache else None
        if db is None:
            db = media.loudness(clip["path"]) if clip.get("has_audio") else []
        dur = clip["duration"]
        loud = clip.get("loud", [])
        sents = [strip_lead_in(w) for w in sentences(clip.get("words", []))]
        spans = []
        for i, (words, dropped) in enumerate(sents):
            # Never cut into the neighbouring sentence's words.
            lo = sents[i - 1][0][-1]["e"] if i else 0.0
            hi = sents[i + 1][0][0]["s"] if i + 1 < len(sents) else dur
            c = _piece(clip, words, db, lo, hi, loud)
            if not c:
                continue
            c["dropped_start"] = dropped
            spans.append((c["start"], c["end"]))
            cands.append(c)
            # Short clauses inside long sentences can serve as the hook.
            for clause in clauses(words):
                if len(clause) < len(words):
                    a, b = words.index(clause[0]), words.index(clause[-1])
                    clo = words[a - 1]["e"] if a else lo
                    chi = words[b + 1]["s"] if b + 1 < len(words) else hi
                    h = _piece(clip, strip_lead_in(clause)[0], db, clo, chi, loud, kind="clause")
                    if h and (h["problem"] or h["reveal"]):
                        cands.append(h)
        # Loud moments with nobody talking: engine firing, revs, impacts.
        for ls, le in loud if clip.get("words") else []:
            if _overlap(ls, le, spans) / max(le - ls, 0.01) > 0.5:
                continue
            s, e = max(0, ls - 0.3), min(dur, le + 0.5)
            cands.append({"src": clip["id"], "start": round(s, 2), "end": round(e, 2), "dur": round(e - s, 2),
                          "kind": "action", "text": "[loud moment, no talking]", "score": 2.5,
                          "problem": 0, "reveal": 0, "fillers": 0, "approx": False, "flags": []})
        # No transcript at all: fall back to the non-quiet stretches.
        if not clip.get("words"):
            t = 0.0
            for qs, qe in clip.get("silences", []) + [(dur, dur)]:
                if qs - t > 0.5:
                    cands.append({"src": clip["id"], "start": round(t, 2), "end": round(qs, 2),
                                  "dur": round(qs - t, 2), "kind": "sound", "text": "[no transcript]",
                                  "score": 1.0, "problem": 0, "reveal": 0, "fillers": 0,
                                  "approx": False, "flags": []})
                t = qe
    cands.sort(key=lambda c: (c["src"], c["start"]))
    for i, c in enumerate(cands):
        c["id"] = f"m{i + 1}"
    mark_retakes(cands)
    _propagate_retakes(cands)
    return cands


def _sim(a, b):
    ta = [norm(w) for w in a.split() if norm(w) not in FILLERS]
    tb = [norm(w) for w in b.split() if norm(w) not in FILLERS]
    if not ta or not tb:
        return 0.0
    return difflib.SequenceMatcher(None, ta, tb).ratio()


def mark_retakes(cands):
    """Keep the last take. A sentence is a retake when a later one within 30 s
    says nearly the same thing, or starts the same way and goes further."""
    speech = [c for c in cands if c["kind"] == "speech"]
    for i, c in enumerate(speech):
        low = c["text"].lower()
        if any(re.search(p, low) for p in RETAKE_CUES):
            c["flags"].append("retake cue")
            if i > 0 and speech[i - 1]["src"] == c["src"]:
                speech[i - 1]["flags"].append("retake")
        for d in speech[i + 1:i + 4]:
            if d["src"] != c["src"] or d["start"] - c["end"] > 30:
                break
            first = lambda t: [norm(w) for w in t.split()[:3]]
            if _sim(c["text"], d["text"]) > 0.6 or (
                    len(c["text"].split()) >= 3 and first(c["text"]) == first(d["text"])):
                c["flags"].append("retake")
                break


def _propagate_retakes(cands):
    for c in cands:
        if c["kind"] == "clause":
            for p in cands:
                if (p["kind"] == "speech" and p["src"] == c["src"] and p["start"] <= c["start"]
                        and c["end"] <= p["end"] and not usable(p)):
                    c["flags"].append("retake")
                    break


def usable(c):
    return not ({"retake", "retake cue"} & set(c["flags"]))


def pick_hook(cands):
    """Best short line naming the problem or the result. A clause pulled out of a
    longer sentence plays as a teaser; the full sentence can still come later."""
    pool = [c for c in cands if usable(c) and c["kind"] in ("speech", "clause")
            and 1.2 <= c["dur"] <= 6 and (c["problem"] or c["reveal"])]
    pool = pool or [c for c in cands if usable(c) and c["kind"] != "clause"]
    return max(pool, key=lambda c: (c["score"] / (1 + 0.1 * c["dur"]), -c["start"])) if pool else None


def build_cut(cands, sources, name, t):
    order = {s["id"]: i for i, s in enumerate(sources)}
    pool = [c for c in cands if usable(c) and c["kind"] != "clause"]
    material = sum(c["dur"] for c in pool)
    if material < t.get("needs_material_s", 0):
        return {"target": name, "label": t["label"], "skipped": True,
                "notes": [f"Only {material:.0f} s of usable footage; needs {t['needs_material_s']} s."]}
    hook = pick_hook([c for c in cands if usable(c)])
    chosen = [hook] if hook else []
    total = hook["dur"] if hook else 0
    if t.get("cold_open"):
        # Long videos keep everything in order and repeat the hook as a cold open.
        rest = sorted(pool, key=lambda c: (order[c["src"]], c["start"]))
    else:
        rest = sorted((c for c in pool if c is not hook), key=lambda c: -c["score"])
    picked = []
    for c in rest:
        if total + c["dur"] <= t["max_s"]:
            picked.append(c)
            total += c["dur"]
    if not t.get("cold_open"):
        picked.sort(key=lambda c: (order[c["src"]], c["start"]))
    segs = chosen + picked
    notes = []
    if total < t["min_s"]:
        notes.append(f"Only {total:.1f} s, under the {t['min_s']} s minimum. Needs more footage.")
    if any(c["approx"] for c in segs):
        notes.append("Word timings are estimated from an SRT; check the cut points.")
    return {
        "target": name, "label": t["label"], "aspect": t["aspect"], "skipped": False,
        "duration": round(total, 2), "hook": hook["id"] if hook else None,
        "segments": [{"id": c["id"], "src": c["src"], "start": c["start"], "end": c["end"],
                      "text": c["text"], "why": ("hook" if c["kind"] != "clause" else "hook, teaser clip")
                      if c is hook else f"score {c['score']}"}
                     for c in segs],
        "notes": notes,
    }


def load_targets(jb):
    with open(os.path.join(HERE, "targets.json")) as f:
        targets = json.load(f)
    best = (jb.get("trends") or {}).get("best_length")
    return {k: v for k, v in targets.items()
            if not v.get("only_if_best_length") or v["only_if_best_length"] == best}


def report(jb):
    src = {s["id"]: s["name"] for s in jb["sources"]}
    lines = [f"# Cut report: {jb['id']}", ""]
    tr = jb.get("trends") or {}
    if tr.get("by_length"):
        lines.append(f"Trends ({tr.get('snapshot')}): " + ", ".join(
            f"{b['length']} median {b['median_plays']:,.0f} plays" for b in tr["by_length"]))
        lines.append("")
    for name, cut in jb["cuts"].items():
        lines.append(f"## {cut['label']} ({name})")
        if cut.get("skipped"):
            lines += [f"- skipped: {n}" for n in cut["notes"]] + [""]
            continue
        lines.append(f"{cut['duration']} s, {len(cut['segments'])} pieces")
        for s in cut["segments"]:
            lines.append(f"- `{s['id']}` {src[s['src']]} {s['start']:.2f}-{s['end']:.2f} ({s['why']}): {s['text']}")
        lines += [f"- note: {n}" for n in cut["notes"]] + [""]
    lines.append("## Everything found")
    for c in jb["candidates"]:
        fl = f" [{', '.join(c['flags'])}]" if c["flags"] else ""
        lines.append(f"- `{c['id']}` {src[c['src']]} {c['start']:.2f}-{c['end']:.2f} "
                     f"score {c['score']}{fl}: {c['text']}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)
    jb = J.load(a.job)
    if not a.report:
        jb["candidates"] = find_candidates(jb)
        jb["cuts"] = {name: build_cut(jb["candidates"], jb["sources"], name, t)
                      for name, t in load_targets(jb).items()}
        J.mark(jb, "cutter", "done", auto=True)
        J.save(jb)
    text = report(jb)
    with open(os.path.join(J.job_dir(a.job), "cut-report.md"), "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
