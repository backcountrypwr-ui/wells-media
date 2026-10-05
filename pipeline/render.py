"""Render a cut list to a rough video with plain burned-in captions.

    python3 -m pipeline.render --job <job_id> [--target ig_reel ...] [--fill blur|crop]

Rough means: the right pieces in the right order, at the platform's size,
with readable captions so the cut can be judged. Styling, grade, music and
privacy blur are later stages.
"""
import argparse
import os
import shutil
import subprocess
import tempfile

from . import job as J
from .transcribe import FILLERS, norm

SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080)}
FPS = 30
FONT = "FreeSans"


def _fit(src, W, H, fill):
    sw, sh = src.get("width", W), src.get("height", H)
    same = abs(sw / sh - W / H) < 0.02
    cover = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    if same or fill == "crop":
        return f"[0:v]{cover},fps={FPS}[v]"
    # Landscape into vertical (or the reverse): sharp video over a blurred copy.
    return (f"[0:v]split[a][b];[a]{cover},boxblur=30:2[bg];"
            f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS}[v]")


def _segment(src, seg, out, W, H, fill):
    d = round(seg["end"] - seg["start"], 3)
    fade = min(0.03, d / 4)
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(seg["start"]), "-t", str(d), "-i", src["path"]]
    if not src.get("has_audio", True):
        cmd += ["-f", "lavfi", "-t", str(d), "-i", "anullsrc=r=48000:cl=stereo"]
    a_in = "[0:a]" if src.get("has_audio", True) else "[1:a]"
    fc = (_fit(src, W, H, fill) + f";{a_in}aresample=48000,"
          f"afade=t=in:d={fade},afade=t=out:st={max(0, d - fade)}:d={fade}[a]")
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(d),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2", out]
    subprocess.run(cmd, check=True)


def _ass_time(t):
    t = max(0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def caption_events(jb, cut, max_words=3):
    """Word timings remapped onto the cut's timeline, grouped 2-3 words at a time."""
    srcs = {s["id"]: s for s in jb["sources"]}
    words, off = [], 0.0
    for seg in cut["segments"]:
        inside = [w for w in srcs[seg["src"]].get("words", [])
                  if w["s"] >= seg["start"] - 0.05 and w["e"] <= seg["end"] + 0.1]
        # Estimated timings can pull in a dropped lead-in word; start where the text starts.
        first = norm(seg.get("text", "").split()[0]) if seg.get("text", "").split() else None
        for k, w in enumerate(inside[:4]):
            if norm(w["w"]) == first:
                inside = inside[k:]
                break
        for w in inside:
            if norm(w["w"]) not in FILLERS:
                words.append({"w": w["w"].strip(",").strip(), "s": off + max(0, w["s"] - seg["start"]),
                              "e": off + min(w["e"], seg["end"]) - seg["start"]})
        off += seg["end"] - seg["start"]
    events, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        brk = len(cur) >= max_words or w["w"][-1:] in ".!?" or nxt is None or nxt["s"] - w["e"] > 0.5
        if brk:
            end = min(nxt["s"], cur[-1]["e"] + 0.3) if nxt else cur[-1]["e"] + 0.3
            events.append((cur[0]["s"], end, " ".join(x["w"] for x in cur)))
            cur = []
    return events


def write_ass(events, path, W, H):
    size = int(W * 0.083)
    margin = int(H * 0.28) if H > W else int(H * 0.08)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT},{size},&H00FFFFFF,&H0000C4FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{max(4, size // 14)},0,2,60,60,{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(path, "w") as f:
        f.write(head)
        for s, e, text in events:
            text = text.upper().replace("{", "(").replace("}", ")")
            f.write(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Cap,,0,0,0,,{text}\n")


def render(jb, name, fill="blur", captions=True):
    cut = jb["cuts"][name]
    if cut.get("skipped") or not cut.get("segments"):
        return None
    W, H = SIZES[cut["aspect"]]
    srcs = {s["id"]: s for s in jb["sources"]}
    out_dir = os.path.join(J.job_dir(jb["id"]), "out")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{name}-rough.mp4")
    tmp = tempfile.mkdtemp(prefix="render-")
    try:
        parts = []
        for i, seg in enumerate(cut["segments"]):
            p = os.path.join(tmp, f"{i:03d}.mp4")
            _segment(srcs[seg["src"]], seg, p, W, H, fill)
            parts.append(p)
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        joined = os.path.join(tmp, "joined.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-c", "copy", joined], check=True)
        if captions:
            ass = os.path.join(tmp, "caps.ass")
            write_ass(caption_events(jb, cut), ass, W, H)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", joined, "-vf", f"ass={ass}",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-c:a", "copy", "-movflags", "+faststart", out], check=True)
        else:
            shutil.copy(joined, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cut["render"] = {"rough": os.path.relpath(out, J.ROOT), "fill": fill, "at": J.now()}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--target", nargs="*")
    ap.add_argument("--fill", choices=["blur", "crop"], default="blur",
                    help="landscape footage in a vertical video: blurred sides or centre crop")
    ap.add_argument("--no-captions", action="store_true")
    a = ap.parse_args(argv)
    jb = J.load(a.job)
    for name in a.target or list(jb["cuts"]):
        out = render(jb, name, a.fill, not a.no_captions)
        print(f"{name}: {out or 'skipped'}")
    J.save(jb)


if __name__ == "__main__":
    main()
