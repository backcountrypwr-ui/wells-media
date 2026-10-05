# wells-media
Finished videos for posting, and the editing pipeline that makes them.

## Editing pipeline
Raw footage goes through role agents that share one job file, `jobs/<job>/job.json`:

| Stage | Who | Status |
|---|---|---|
| 0 intake | logs clips, transcript, quiet and loud moments, trends from wells-dashboard | built |
| 1 cutter | silence, filler, retakes, hook first, cut list per platform, rough render | built |
| 2 visuals | styled captions, grade, zooms, callouts, privacy blur (`python3 -m pipeline.visuals`) | built |
| 3 audio | voice cleanup, loudness, royalty-free music bed (`python3 -m pipeline.audio`) | built |
| 4 packager | thumbnail, title, caption, hashtags, approval card | planned |

Nothing is ever posted without Wells approving the exact video, caption and account.

Quick start (see `.claude/skills/cutter/SKILL.md` for the full steps):
```
python3 -m pip install -r requirements.txt
python3 -m pipeline.intake --job 2026-10-06-clutch --src raw/clip.mp4 --srt raw/clip.srt
python3 -m pipeline.cut --job 2026-10-06-clutch
python3 -m pipeline.render --job 2026-10-06-clutch
python3 -m unittest discover tests
```
Targets (lengths, sizes) live in `pipeline/targets.json`.
