"""Stage 0: log raw clips into a new job.

    python3 -m pipeline.intake --job 2026-10-06-clutch \
        --src raw/clip1.mp4 raw/clip2.mp4 [--srt clip1.srt clip2.srt] [--whisper]

For each clip: duration, size, fps, quiet stretches, loud moments and a
word-level transcript. Also stores the current trends from wells-dashboard.
Media files stay where they are; the job only records their paths.
"""
import argparse
import os

from . import job as J
from . import media, transcribe, trends


def log_clip(path, srt=None, use_whisper=False):
    info = media.probe(path)
    clip = {"path": os.path.abspath(path), "name": os.path.basename(path), **info}
    clip.update(media.analyse(path) if info["has_audio"] else {"silences": [], "loud": []})
    words, source = [], None
    if srt:
        with open(srt) as f:
            words, source = transcribe.from_srt(f.read()), "srt"
    elif use_whisper and info["has_audio"]:
        words, source = transcribe.from_whisper(path), "whisper"
    clip["transcript_source"] = source
    clip["words"] = words
    clip["text"] = " ".join(w["w"] for w in words)
    return clip


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--src", nargs="+", required=True)
    ap.add_argument("--srt", nargs="*", default=[], help="one SRT per --src, in the same order")
    ap.add_argument("--whisper", action="store_true", help="transcribe locally with faster-whisper")
    ap.add_argument("--note", default="")
    ap.add_argument("--dashboard", default=trends.DEFAULT_DASH)
    a = ap.parse_args(argv)
    if a.srt and len(a.srt) != len(a.src):
        ap.error("give one --srt per --src")

    jb = J.new_job(a.job, a.note)
    jb["trends"] = trends.read(a.dashboard)
    for i, src in enumerate(a.src):
        clip = log_clip(src, a.srt[i] if a.srt else None, a.whisper)
        clip["id"] = f"c{i + 1}"
        jb["sources"].append(clip)
        print(f"{clip['id']} {clip['name']}: {clip['duration']}s {clip.get('width')}x{clip.get('height')}, "
              f"{len(clip['words'])} words ({clip['transcript_source'] or 'no transcript'}), "
              f"{len(clip['silences'])} quiet stretches, {len(clip['loud'])} loud moments")
    J.mark(jb, "intake", "done", clips=len(jb["sources"]))
    J.save(jb)
    print("wrote", J.job_path(a.job))


if __name__ == "__main__":
    main()
