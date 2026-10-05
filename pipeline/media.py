"""ffmpeg helpers: probe a clip and read its loudness over time."""
import json
import subprocess

import numpy as np

SR = 16000
HOP = 0.05  # seconds per loudness frame


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True)


def probe(path):
    out = run(["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", path]).stdout
    info = json.loads(out)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    res = {"duration": round(float(info["format"]["duration"]), 3), "has_audio": a is not None}
    if v:
        w, h = int(v["width"]), int(v["height"])
        # Phones store portrait video as landscape plus a rotation flag.
        rot = 0
        for sd in v.get("side_data_list", []):
            if "rotation" in sd:
                rot = abs(int(sd["rotation"]))
        rot = rot or abs(int(v.get("tags", {}).get("rotate", 0)))
        if rot in (90, 270):
            w, h = h, w
        num, den = v.get("avg_frame_rate", "30/1").split("/")
        res.update(width=w, height=h, fps=round(int(num) / max(int(den), 1), 2))
    return res


def loudness(path):
    """Loudness in dBFS, one value per HOP seconds."""
    pcm = run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR),
               "-f", "s16le", "-"]).stdout
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(SR * HOP)
    frames = len(x) // n
    if frames == 0:
        return np.array([])
    rms = np.sqrt(np.mean(x[: frames * n].reshape(frames, n) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms)


def regions(mask, min_len):
    """Runs of True in a frame mask, as (start_s, end_s), at least min_len long."""
    out, start = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            if (i - start) * HOP >= min_len:
                out.append((round(start * HOP, 2), round(i * HOP, 2)))
            start = None
    return out


def analyse(path, min_silence=0.4):
    """Noise floor, silences and loud moments (engine, impacts) for one clip."""
    db = loudness(path)
    if len(db) == 0:
        return {"floor_db": None, "silences": [], "loud": []}
    floor = float(np.percentile(db, 10))
    speech = float(np.percentile(db, 70))
    # Shop footage is never truly silent, so "silence" is relative to the clip.
    quiet = db < floor + max(6.0, (speech - floor) * 0.3)
    # Loud = well above normal talking level: an engine firing, a rev, a bang.
    loud = db > max(float(np.percentile(db, 95)) - 1.0, speech + 6.0)
    return {
        "floor_db": round(floor, 1),
        "speech_db": round(speech, 1),
        "silences": regions(quiet, min_silence),
        "loud": regions(loud, 0.3),
    }

