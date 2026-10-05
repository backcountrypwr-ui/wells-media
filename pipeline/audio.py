"""Stage 3: audio. Cleans the voice, adds a music bed under it, and sets platform loudness.

    python3 -m pipeline.audio --job <job_id> --target ig_reel [--music pipeline/music/x.m4a | --no-music]

Reads out/<target>-visuals.mp4 (or the rough cut if visuals hasn't run) and writes
out/<target>-audio.mp4 with the video stream copied untouched. Settings are in style.json "audio":
- voice: rumble cut, light denoise, gentle compression
- music: looped to length, set music_under_db below the voice, and ducked further while talking
- final loudness: lufs / true_peak (Instagram and YouTube both play back around -14 LUFS)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile

from . import job as J
from . import media
from .visuals import load_style

VOICE = ("highpass=f=80,afftdn=nf=-25,"
         "acompressor=threshold=-20dB:ratio=3:attack=10:release=150:makeup=2")


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def measure(path):
    """Integrated loudness (LUFS) and true peak (dBTP) of a file's audio."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, check=True)
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr).group(0))
    return float(m["input_i"]), float(m["input_tp"])


def _normalize(src, out, lufs, tp, extra=""):
    """Two-pass loudnorm so the result lands on the target instead of near it."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-af",
                        f"{extra}loudnorm=I={lufs}:TP={tp}:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, check=True)
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr).group(0))
    _ff("-i", src, "-af",
        f"{extra}loudnorm=I={lufs}:TP={tp}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
        ":linear=true", "-ar", "48000", "-ac", "2", out)


def mix(video, out, au, music=None):
    """Write `out`: the video stream from `video`, with cleaned voice plus an optional music bed."""
    dur = media.probe(video)["duration"]
    tmp = tempfile.mkdtemp(prefix="audio-")
    try:
        voice = os.path.join(tmp, "voice.wav")
        _normalize(video, voice, au["lufs"], au["true_peak"], extra=VOICE + ",")
        final_audio = voice
        if music:
            bed = os.path.join(tmp, "bed.wav")
            fade = min(1.5, dur / 4)
            _ff("-stream_loop", "-1", "-i", music, "-t", f"{dur:.3f}", "-af",
                f"afade=t=in:d=0.4,afade=t=out:st={dur - fade:.3f}:d={fade:.3f}",
                "-ar", "48000", "-ac", "2", os.path.join(tmp, "loop.wav"))
            _normalize(os.path.join(tmp, "loop.wav"), bed, au["lufs"] - au["music_under_db"], -6)
            mixed = os.path.join(tmp, "mixed.wav")
            # The voice keys a compressor on the music, so the bed dips further while Wells talks.
            _ff("-i", voice, "-i", bed, "-filter_complex",
                "[0:a]asplit=2[v][key];"
                f"[1:a][key]sidechaincompress=threshold=0.03:ratio={au['duck_ratio']}:attack=20:release=400[m];"
                "[v][m]amix=inputs=2:normalize=0:duration=first[a]",
                "-map", "[a]", mixed)
            final_audio = os.path.join(tmp, "final.wav")
            _normalize(mixed, final_audio, au["lufs"], au["true_peak"])
        _ff("-i", video, "-i", final_audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def run(jb, name, music=None, st=None):
    st = st or load_style()
    au = st["audio"]
    out_dir = os.path.join(J.job_dir(jb["id"]), "out")
    src = os.path.join(out_dir, f"{name}-visuals.mp4")
    if not os.path.exists(src):
        src = os.path.join(out_dir, f"{name}-rough.mp4")
    rec = jb.setdefault("audio", {}).setdefault(name, {})
    if music is None:
        music = rec.get("music", au.get("music"))
    if music and not os.path.isabs(music):
        music = os.path.join(J.ROOT, music)
    out = mix(src, os.path.join(out_dir, f"{name}-audio.mp4"), au, music or None)
    lufs, tp = measure(out)
    rec.update({"file": os.path.relpath(out, J.ROOT), "from": os.path.relpath(src, J.ROOT),
                "music": os.path.relpath(music, J.ROOT) if music else "",
                "lufs": round(lufs, 1), "true_peak": round(tp, 1), "at": J.now()})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--target", nargs="+", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--music", help="music file (default: style.json audio.music)")
    g.add_argument("--no-music", action="store_true")
    a = ap.parse_args(argv)
    jb = J.load(a.job)
    for name in a.target:
        out = run(jb, name, "" if a.no_music else a.music)
        r = jb["audio"][name]
        print(f"{name} {out}  {r['lufs']} LUFS, peak {r['true_peak']} dBTP")
    J.mark(jb, "audio", "done", targets=a.target)
    J.save(jb)


if __name__ == "__main__":
    main()
