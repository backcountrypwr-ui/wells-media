"""Stage 4: packager. Cover/thumbnail, per-platform copy, and the approval card.

    python3 -m pipeline.package --job <job_id> --target ig_reel [--cover-at 1.2]

The agent writes the copy into job.json first (titles, captions and hashtags are judgement calls):

    "package": {"ig_reel": {"cover_text": "ROLLED IT.", "copy": {
        "instagram": {"caption": "...", "hashtags": ["#canam"]},
        "facebook": {"caption": "...", "hashtags": []}}}}

This script then picks a sharp, clean frame for the cover (no captions; privacy blur kept), puts the
cover text on it in the house style, checks the copy against platform limits and privacy patterns,
and writes out/<target>-approval.md plus job.approval items. Each item pins the exact video by
sha256, so the poster can refuse anything that changed after Wells approved it.
Nothing here posts.
"""
import argparse
import copy as _copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np

from . import job as J
from . import render as R
from . import trends
from . import visuals as V

HERE = os.path.dirname(os.path.abspath(__file__))

# Things that must never reach a caption without Wells's say-so.
PRIVACY = [
    (re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b"), "looks like a VIN"),
    (re.compile(r"\b\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b"), "looks like a phone number"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "looks like an email address"),
]


def load_config():
    with open(os.path.join(HERE, "package.json")) as f:
        return json.load(f)


def final_video(jb, name):
    out = os.path.join(J.job_dir(jb["id"]), "out")
    for kind in ("audio", "visuals", "rough"):
        p = os.path.join(out, f"{name}-{kind}.mp4")
        if os.path.exists(p):
            return p, kind
    raise FileNotFoundError(f"no rendered video for {name}; run render/visuals/audio first")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _timeline(cut):
    t, out = 0.0, []
    for seg in cut["segments"]:
        d = seg["end"] - seg["start"]
        out.append((t, t + d, seg))
        t += d
    return out


def _gray(src_path, at, w=180, h=320):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", src_path, "-frames:v", "1",
                        "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(h, w).astype(float) if r.stdout else None


def sharpness(img):
    """Variance of a Laplacian: higher means less motion blur."""
    lap = img[1:-1, 1:-1] * 4 - img[:-2, 1:-1] - img[2:, 1:-1] - img[1:-1, :-2] - img[1:-1, 2:]
    return float(lap.var())


def pick_cover(jb, cut, within=None, step=0.25):
    """Sharpest frame in the cut (first `within` seconds if given), as (cut time, segment)."""
    srcs = {s["id"]: s for s in jb["sources"]}
    best = (-1.0, 0.0, None)
    for t0, t1, seg in _timeline(cut):
        if within is not None and t0 >= within:
            break
        t = t0 + 0.1
        while t < min(t1, within or t1) - 0.1:
            img = _gray(srcs[seg["src"]]["path"], seg["start"] + t - t0)
            if img is not None:
                s = sharpness(img)
                if s > best[0]:
                    best = (s, t, seg)
            t += step
    return best[1], best[2]


def render_cover(jb, cut, at, text, out, st, cfg):
    """A clean frame at cut time `at` (graded, privacy blur kept) with the cover text on top."""
    W, H = R.SIZES[cut["aspect"]]
    srcs = {s["id"]: s for s in jb["sources"]}
    for t0, t1, seg in _timeline(cut):
        if t0 <= at < t1:
            break
    s = seg["start"] + at - t0
    one = dict(seg, start=s, end=min(seg["end"], s + 0.2))
    tmp = tempfile.mkdtemp(prefix="cover-")
    try:
        clip = os.path.join(tmp, "f.mp4")
        R._segment(srcs[seg["src"]], one, clip, W, H, "blur", post=st["grade"])
        cst = _copy.deepcopy(st)
        cst["hook"].update(size=cfg["cover"]["size"], margin_v=cfg["cover"]["margin_v"])
        ass = os.path.join(tmp, "c.ass")
        if text:
            V.write_ass(ass, W, H, cst, [(0.0, 5.0, "Hook", V._esc(text.upper()))])
            vf = f"ass={ass}:fontsdir={V.FONTS}"
        else:
            vf = "null"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip, "-frames:v", "1", "-vf", vf,
                        "-q:v", "2", out], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def check_copy(platform, entry, limits):
    """Problems with one platform's copy, as readable strings (empty list = fine)."""
    lim, issues = limits.get(platform, {}), []
    tags = entry.get("hashtags", [])
    full = " ".join([entry.get("title", ""), entry.get("caption", ""), " ".join(tags)])
    if "title" in lim and not entry.get("title"):
        issues.append("needs a title")
    if len(entry.get("title", "")) > lim.get("title", 10**6):
        issues.append(f"title over {lim['title']} characters")
    body = entry.get("caption", "") + ("\n\n" + " ".join(tags) if tags else "")
    if len(body) > lim.get("caption", 10**6):
        issues.append(f"caption over {lim['caption']} characters")
    if len(tags) > lim.get("hashtags", 10**6):
        issues.append(f"more than {lim['hashtags']} hashtags")
    if any(not re.fullmatch(r"#\w+", t) for t in tags):
        issues.append("hashtags must be single words starting with #")
    if lim.get("require") and lim["require"].lower() not in full.lower():
        issues.append(f"missing {lim['require']}")
    for rx, why in PRIVACY:
        if rx.search(full):
            issues.append(f"privacy: {why}")
    return issues


def card(jb, name, items, insights, cover):
    cut = jb["cuts"][name]
    lines = [f"# Approval card: {jb['id']} / {name}", "",
             f"Video: `{items[0]['video']}` ({cut['duration']:.1f} s)  ",
             f"sha256: `{items[0]['sha256'][:16]}…`  ",
             f"Cover: `{cover}`", "",
             "Nothing is posted until Wells approves the exact video, caption and account below.", ""]
    for it in items:
        lines += [f"## {it['account']}", ""]
        if it.get("title"):
            lines += [f"**Title:** {it['title']}", ""]
        lines += ["**Caption:**", "", "```", it["caption"] + ("\n\n" + " ".join(it["hashtags"])
                                                             if it["hashtags"] else ""), "```", ""]
        if it["issues"]:
            lines += ["**Fix before approval:** " + "; ".join(it["issues"]), ""]
    if jb.get("privacy"):
        lines += ["## Privacy notes", ""] + [f"- {p}" for p in jb["privacy"]] + [""]
    if insights and not insights.get("error"):
        lines += [f"## What the copy is based on ({insights['snapshot']})", "",
                  f"- {insights['with_hashtags']} of your {insights['reels_counted']} reels used hashtags;"
                  f" median caption is {insights['median_caption_words']:g} words.",
                  "- Top reels by plays: " + "; ".join(f"\"{t['cap']}\" ({t['plays']:,})"
                                                       for t in insights["top"][:4]), ""]
    return "\n".join(lines)


def run(jb, name, cover_at=None, dash=trends.DEFAULT_DASH, st=None, cfg=None):
    st, cfg = st or V.load_style(), cfg or load_config()
    cut = jb["cuts"][name]
    pk = jb.setdefault("package", {}).setdefault(name, {})
    copy = pk.get("copy") or {}
    platforms = cfg["platforms"].get(name, [])
    missing = [p for p in platforms if p not in copy]
    if missing:
        raise SystemExit(f"write package.{name}.copy for: {', '.join(missing)} (see the packager skill)")
    video, stage = final_video(jb, name)
    out_dir = os.path.dirname(video)

    if cover_at is None:
        cover_at = pk.get("cover_at")
    if cover_at is None:
        cover_at, _ = pick_cover(jb, cut, within=min(8.0, cut["duration"]))
    text = pk.get("cover_text", jb.get("visuals", {}).get(name, {}).get("hook_text", ""))
    cover = render_cover(jb, cut, cover_at, text, os.path.join(out_dir, f"{name}-cover.jpg"), st, cfg)

    digest = sha256(video)
    items = []
    for p in platforms:
        e = copy[p]
        items.append({"platform": p, "account": cfg["accounts"][p], "target": name,
                      "video": os.path.relpath(video, J.ROOT), "video_stage": stage, "sha256": digest,
                      "cover": os.path.relpath(cover, J.ROOT), "title": e.get("title", ""),
                      "caption": e.get("caption", ""), "hashtags": e.get("hashtags", []),
                      "issues": check_copy(p, e, cfg["limits"]), "approved": False})
    insights = trends.captions(dash) if os.path.isdir(dash) else {"error": "no dashboard"}
    md = os.path.join(out_dir, f"{name}-approval.md")
    with open(md, "w") as f:
        f.write(card(jb, name, items, insights, os.path.relpath(cover, J.ROOT)) + "\n")

    pk.update({"cover": os.path.relpath(cover, J.ROOT), "cover_at": round(cover_at, 2),
               "cover_text": text, "card": os.path.relpath(md, J.ROOT), "at": J.now()})
    ap = jb.setdefault("approval", {"approved": False, "by": None, "at": None, "items": []})
    ap["items"] = [i for i in ap.get("items", []) if i.get("target") != name] + items
    ap.update(approved=False, by=None, at=None)
    return items, md


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--target", nargs="+", required=True)
    ap.add_argument("--cover-at", type=float, help="cut time (s) for the cover frame")
    ap.add_argument("--dashboard", default=trends.DEFAULT_DASH)
    a = ap.parse_args(argv)
    jb = J.load(a.job)
    for name in a.target:
        items, md = run(jb, name, a.cover_at, a.dashboard)
        for it in items:
            print(f"{name} → {it['account']}: {'OK' if not it['issues'] else '; '.join(it['issues'])}")
        print("card:", md)
    J.mark(jb, "packager", "done", targets=a.target)
    J.mark(jb, "approval", "waiting")
    J.save(jb)


if __name__ == "__main__":
    main()
