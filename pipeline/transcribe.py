"""Word-level transcripts.

Two backends:
- "whisper": faster-whisper run locally. Needs its model download
  (huggingface.co) to be allowed by the network.
- "srt": an SRT file, e.g. exported from Descript. SRT only has timings per
  caption line, so word times inside a line are spread by character count.
  Good enough for picking sentences; the cutter snaps cuts to quiet frames.
"""
import re

FILLERS = {"um", "uh", "erm", "uhm", "hmm", "mm", "ah"}


def norm(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def _ts(s):
    h, m, rest = s.strip().split(":")
    sec, ms = rest.replace(".", ",").split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def from_srt(text):
    words = []
    blocks = re.split(r"\n\s*\n", text.strip().replace("\r", ""))
    for b in blocks:
        lines = [l for l in b.split("\n") if l.strip()]
        tline = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if tline is None:
            continue
        a, b_ = lines[tline].split("-->")
        start, end = _ts(a), _ts(b_)
        toks = " ".join(lines[tline + 1:]).split()
        if not toks:
            continue
        total = sum(len(t) + 1 for t in toks)
        t = start
        for tok in toks:
            d = (end - start) * (len(tok) + 1) / total
            words.append({"w": tok, "s": round(t, 2), "e": round(t + d, 2), "approx": True})
            t += d
    return words


def from_whisper(path, model="small.en"):
    from faster_whisper import WhisperModel

    m = WhisperModel(model, compute_type="int8")
    segs, _ = m.transcribe(path, word_timestamps=True, vad_filter=True)
    words = []
    for seg in segs:
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)})
    return words


def sentences(words, max_gap=0.8):
    """Group words into sentences on end punctuation or a long pause."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        ends = re.search(r"[.!?]['\"]?$", w["w"])
        gap = nxt is not None and nxt["s"] - w["e"] > max_gap
        if ends or gap or nxt is None:
            out.append(cur)
            cur = []
    return out
