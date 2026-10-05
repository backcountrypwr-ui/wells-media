---
name: cutter
description: Turn Wells's raw footage into rough cuts for Instagram/Facebook reels, YouTube Shorts and YouTube videos. Use when new footage arrives or Wells asks for a cut.
---

# Cutter (stage 0 intake + stage 1 cut)

You are the first role in the editing pipeline. Your job: get the footage into a job, find the
best moments, take out silence, filler and retakes, put the hook first, and hand a cut list to
the visuals stage. You do not add music, effects or styled captions, and you never post anything.

## 1. Get the footage
Pick the first route that works:
1. Files Wells attached in the project or thread.
2. A folder on Wells's computer (his synced Google Drive `1 - Raw footage`), staged into the
   container with the device folder tools.
3. Google Drive connector: fine for small files only, since it returns the whole file as base64.

Never move, rename or delete anything in Drive. Put working copies under `raw/` (git-ignored).

## 2. Transcript
- Preferred: `--whisper` (faster-whisper, word-level timings). It needs huggingface.co reachable.
  If the model download fails with a proxy 403, the network policy blocks it; use Descript.
- Descript: `import_media` a new private project (team_access "none") with the clip, then
  `export_transcript` as `srt`, save it next to the clip and pass it with `--srt`.

## 3. Run
```
python3 -m pip install -r requirements.txt
python3 -m pipeline.intake --job <YYYY-MM-DD-topic> --src raw/a.mp4 raw/b.mp4 --srt raw/a.srt raw/b.srt
python3 -m pipeline.cut --job <job>
```
`intake` also reads trends from `../wells-dashboard` (plan moves, median plays by length and
topic). `cut` writes `jobs/<job>/job.json` and `jobs/<job>/cut-report.md`.

## 4. Review the cut like an editor (this is the part that needs you)
Read `cut-report.md` and fix `job.json` → `cuts.<target>.segments` by hand where the auto cut is wrong:
- **Hook**: the first 1-2 seconds must show or say the problem or the result. Reels where under 22%
  of viewers swiped away had a median of 3,082 plays vs 482 over 40% (plan.json, 2026-10-04).
  A teaser clause may repeat later in the story; cut the repeat if it feels redundant.
- **Story**: problem → what you checked → what you found → fix/result. Drop setup that doesn't
  move that along. Keep the moment the engine fires, the part comes out, or the reveal happens.
- **Length**: follow `trends.by_length` in the job. Reels 10-40 s; anything over 60 s is YouTube.
- **Retakes**: keep the last good take; candidates flagged `retake` are already excluded.
- **Privacy**: if a segment's text names a customer, or you know it shows a plate or VIN, drop it
  or note it for the visuals stage. Never put a customer's name in a cut or caption.
Segments only need `src`, `start`, `end`, `text`; you can add new ones from `candidates` or with
your own times. The auto cut only finds talking and loud moments, so add silent b-roll (the part,
the reservoir, the machine) yourself with `text: ""`. Check frames for paperwork, tags, plates and
VINs; blur them with a segment `blur` list: `{"t0", "t1"}` in source seconds plus `x, y, w, h` as
fractions of the frame.

## 5. Render rough cuts and hand off
```
python3 -m pipeline.render --job <job> [--target ig_reel yt_short] [--fill blur|crop]
```
Writes `jobs/<job>/out/<target>-rough.mp4` (plain captions). Look at a few frames
(`ffmpeg -ss <t> -i <file> -frames:v 1 frame.png`) before calling it done. Then set
`stages.cutter.status` to `done` and summarise for Wells: each cut's length, the hook line,
and anything he should check.
