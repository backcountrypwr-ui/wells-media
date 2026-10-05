"""Run with: python3 -m unittest discover tests"""
import os
import shutil
import subprocess
import tempfile
import unittest

from pipeline import cut, media, render, transcribe

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def W(text, start, step=0.4):
    out, t = [], start
    for tok in text.split():
        out.append({"w": tok, "s": round(t, 2), "e": round(t + step - 0.05, 2)})
        t += step
    return out


def clip(words, duration=60.0):
    return {"id": "c1", "name": "x.mp4", "path": "x.mp4", "duration": duration, "has_audio": False,
            "loud": [], "silences": [], "words": words}


def cands_for(words, duration=60.0):
    jb = {"sources": [clip(words, duration)]}
    return cut.find_candidates(jb, db_cache={"c1": []})


class SrtTest(unittest.TestCase):
    def test_spreads_words_inside_cue(self):
        with open(os.path.join(FIX, "coolant.srt")) as f:
            words = transcribe.from_srt(f.read())
        self.assertEqual(words[0]["w"], "Okay,")
        self.assertAlmostEqual(words[0]["s"], 0.04)
        self.assertTrue(all(a["s"] <= b["s"] for a, b in zip(words, words[1:])))
        self.assertTrue(all(w["approx"] for w in words))


class CutterTest(unittest.TestCase):
    def test_strips_lead_in_and_fillers(self):
        c = cands_for(W("Um, okay so the clutch was totally worn out.", 1.0))
        self.assertTrue(c[0]["text"].startswith("the clutch"))

    def test_keeps_last_take(self):
        words = (W("The stator was completely burnt.", 1.0)
                 + W("Let me say that again.", 4.0)
                 + W("The stator was completely burnt up.", 7.0))
        c = [x for x in cands_for(words) if x["kind"] == "speech"]
        self.assertIn("retake", c[0]["flags"])
        self.assertIn("retake cue", c[1]["flags"])
        self.assertTrue(cut.usable(c[2]))

    def test_restarted_sentence_is_a_retake(self):
        words = W("So what I found inside", 1.0) + W("So what I found inside was a mouse nest.", 4.0)
        c = [x for x in cands_for(words) if x["kind"] == "speech"]
        self.assertIn("retake", c[0]["flags"])

    def test_hook_first_and_length_cap(self):
        words = (W("I pulled the cover off this morning to check it out.", 1.0)
                 + W("And look, the whole clutch basket was destroyed.", 7.0)
                 + W("Then I ordered the parts and put it back together.", 13.0))
        cands = cands_for(words)
        t = {"label": "x", "aspect": "9:16", "min_s": 3, "max_s": 10, "hook_first": True}
        res = cut.build_cut(cands, [clip(words)], "x", t)
        self.assertIn("destroyed", res["segments"][0]["text"])
        self.assertLessEqual(res["duration"], 10)

    def test_long_video_skipped_without_material(self):
        words = W("Short clip about a broken belt.", 1.0)
        t = {"label": "yt", "aspect": "16:9", "min_s": 360, "max_s": 1200, "needs_material_s": 360}
        self.assertTrue(cut.build_cut(cands_for(words), [clip(words)], "yt", t)["skipped"])


class MediaTest(unittest.TestCase):
    """End to end on a generated clip: 2 s tone, 2 s silence, 2 s tone."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "tone.mp4")
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:d=6",
            "-f", "lavfi", "-i", "sine=f=440:d=2", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=2",
            "-f", "lavfi", "-i", "sine=f=440:d=2",
            "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]", "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", self.src], check=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_finds_gap_and_renders_vertical(self):
        info = media.probe(self.src)
        a = media.analyse(self.src)
        self.assertEqual(len(a["silences"]), 1)
        s, e = a["silences"][0]
        self.assertAlmostEqual(s, 2.0, delta=0.15)
        self.assertAlmostEqual(e, 4.0, delta=0.15)

        jb = {"id": "unit", "sources": [{"id": "c1", "path": self.src, "name": "tone.mp4", **info, **a,
                                         "words": []}]}
        cands = cut.find_candidates(jb)
        self.assertEqual([c["kind"] for c in cands], ["sound", "sound"])
        t = {"label": "r", "aspect": "9:16", "min_s": 1, "max_s": 10}
        jb["cuts"] = {"r": cut.build_cut(cands, jb["sources"], "r", t)}
        out_dir = os.path.join(self.dir, "out")
        orig = render.J.job_dir
        render.J.job_dir = lambda _id: out_dir
        try:
            out = render.render(jb, "r", captions=False)
        finally:
            render.J.job_dir = orig
        p = media.probe(out)
        self.assertEqual((p["width"], p["height"]), (1080, 1920))
        self.assertAlmostEqual(p["duration"], 4.0, delta=0.3)


if __name__ == "__main__":
    unittest.main()
