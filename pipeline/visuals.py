"""Stage 2: visuals. Renders a cut in the house style (pipeline/style.json).

    python3 -m pipeline.visuals --job <job_id> --target ig_reel [--hook "ROLLED IT."]

Adds, on top of the cutter's cut list:
- word-by-word captions with the spoken word in the accent colour
- a hook title for the first seconds (job.visuals.<target>.hook_text or --hook)
- part callouts the first time a part is named ("VENT HOSE")
- punch-in zooms on alternating talking pieces, to hide jump cuts
- a light colour grade, and the end card
Privacy blur boxes on segments (from the cutter) are kept.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile

from . import job as J
from . import render as R

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")


def load_style():
    with open(os.path.join(HERE, "style.json")) as f:
        return json.load(f)


def ass_color(hex_rgb):
    h = hex_rgb.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _esc(text):
    return text.replace("{", "(").replace("}", ")")


def caption_lines(words, st):
    """One event per spoken word: the 2-3 word group, current word highlighted."""
    c = st["captions"]
    act, txt = ass_color(st["colors"]["active"]), ass_color(st["colors"]["text"])
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if (len(cur) >= c["max_words"] or w["w"][-1:] in ".!?" or nxt is None
                or nxt["s"] - w["e"] > 0.5):
            groups.append((cur, nxt))
            cur = []
    out = []
    for g, nxt in groups:
        g_end = min(nxt["s"], g[-1]["e"] + 0.3) if nxt else g[-1]["e"] + 0.3
        for k, w in enumerate(g):
            s = w["s"]
            e = g[k + 1]["s"] if k + 1 < len(g) else g_end
            if e - s < 0.04:
                continue
            parts = []
            for j, x in enumerate(g):
                word = _esc(re.sub(r"[.,!?]+$", "", x["w"]).upper())
                if j == k:
                    sc = c["active_scale"]
                    parts.append(f"{{\\c{act}\\fscx{sc}\\fscy{sc}}}{word}{{\\c{txt}\\fscx100\\fscy100}}")
                else:
                    parts.append(word)
            out.append((s, e, "Cap", " ".join(parts)))
    return out


def callout_lines(words, st):
    co = st["callouts"]
    seen, out = set(), []
    text = [R.norm(w["w"]) for w in words]
    for part in sorted(co["parts"], key=len, reverse=True):
        toks = part.split()
        for i in range(len(text) - len(toks) + 1):
            if text[i:i + len(toks)] == toks:
                key = part.replace(" ", "")
                if key not in seen and not any(key in s or s in key for s in seen):
                    seen.add(key)
                    t = words[i]["s"]
                    out.append((t, t + co["seconds"], "Callout", part.upper()))
                break
    return out


def write_ass(path, W, H, st, events):
    f, c, col = st["font"], st["captions"], st["colors"]
    white, act, black, box_txt = (ass_color(col["text"]), ass_color(col["active"]),
                                  ass_color(col["outline"]), ass_color(col["box_text"]))
    cap = int(W * c["size"])
    hook = int(W * st["hook"]["size"])
    call = int(W * st["callouts"]["size"])
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{f},{cap},{white},{white},{black},&H64000000,0,0,0,0,100,100,1,0,1,{c['outline']},2,2,70,70,{int(H * c['margin_v'])},1
Style: Hook,{f},{hook},{box_txt},{box_txt},{act},&H00000000,0,0,0,0,100,100,1,0,3,{int(hook * 0.18)},0,8,80,80,{int(H * st['hook']['margin_v'])},1
Style: Callout,{f},{call},{box_txt},{box_txt},{act},&H00000000,0,0,0,0,100,100,1,0,3,{int(call * 0.22)},0,7,70,70,{int(H * st['callouts']['margin_v'])},1
Style: End,{f},{int(hook * 0.75)},{box_txt},{box_txt},{act},&H00000000,0,0,0,0,100,100,1,0,3,{int(hook * 0.16)},0,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(path, "w") as fh:
        fh.write(head)
        for s, e, style, text in sorted(events):
            layer = {"Cap": 0, "Callout": 1, "Hook": 2, "End": 3}[style]
            fh.write(f"Dialogue: {layer},{R._ass_time(s)},{R._ass_time(e)},{style},,0,0,0,,{text}\n")


def style_cut(jb, name, hook_text=None, st=None):
    st = st or load_style()
    cut = jb["cuts"][name]
    W, H = R.SIZES[cut["aspect"]]
    srcs = {s["id"]: s for s in jb["sources"]}
    vis = jb.setdefault("visuals", {}).setdefault(name, {})
    hook_text = hook_text or vis.get("hook_text")
    out_dir = os.path.join(J.job_dir(jb["id"]), "out")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{name}-visuals.mp4")
    tmp = tempfile.mkdtemp(prefix="visuals-")
    z = st["zoom"]["punch_in"]
    try:
        parts, talk = [], 0
        for i, seg in enumerate(cut["segments"]):
            zoom = seg.get("zoom")
            if zoom is None:
                # Alternate framing on consecutive talking pieces; b-roll and the hook stay wide.
                zoom = z if (seg.get("text") and i > 0 and talk % 2 == 1) else 1.0
                talk += 1 if seg.get("text") else 0
            post = st["grade"]
            if zoom != 1.0:
                post += f",scale={int(W * zoom) // 2 * 2}:{int(H * zoom) // 2 * 2},crop={W}:{H}"
            p = os.path.join(tmp, f"{i:03d}.mp4")
            R._segment(srcs[seg["src"]], seg, p, W, H, "blur", post=post)
            parts.append(p)
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        joined = os.path.join(tmp, "joined.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-c", "copy", joined], check=True)
        total = sum(s["end"] - s["start"] for s in cut["segments"])

        words = R.timeline_words(jb, cut)
        events = caption_lines(words, st) + callout_lines(words, st)
        if hook_text:
            events.append((0.0, st["hook"]["seconds"], "Hook", _esc(hook_text.upper())))
        ec = st["end_card"]
        events.append((max(0, total - ec["seconds"]), total, "End", ec["text"]))
        ass = os.path.join(tmp, "style.ass")
        write_ass(ass, W, H, st, events)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", joined, "-vf", f"ass={ass}:fontsdir={FONTS}",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                        "-c:a", "copy", "-movflags", "+faststart", out], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    vis.update({"file": os.path.relpath(out, J.ROOT), "style": st["name"], "hook_text": hook_text,
                "callouts": [e[3] for e in events if e[2] == "Callout"], "at": J.now()})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--target", nargs="+", required=True)
    ap.add_argument("--hook", help="hook title for the first seconds")
    a = ap.parse_args(argv)
    jb = J.load(a.job)
    for name in a.target:
        print(name, style_cut(jb, name, a.hook))
    J.mark(jb, "visuals", "done", targets=a.target)
    J.save(jb)


if __name__ == "__main__":
    main()
