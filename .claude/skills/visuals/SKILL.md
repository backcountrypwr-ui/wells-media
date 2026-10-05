---
name: visuals
description: Give a cut from the cutter Wells's house look (captions, hook title, callouts, zooms, grade, end card, privacy blur). Use after the cutter stage, before audio.
---

# Visuals (stage 2)

You take a cut list the cutter wrote in `jobs/<job>/job.json` and render it in the house style
from `pipeline/style.json` ("Shop Floor" for now). You don't change which pieces are in the cut.

## Steps
1. Read the cut (`cuts.<target>.segments`) and `cut-report.md`.
2. **Hook title**: write 2-5 words that state the problem or the result, in Wells's words
   ("ROLLED IT. COOLANT EVERYWHERE."). Save it as `visuals.<target>.hook_text`, or pass `--hook`.
3. **Privacy**: look at frames from every segment (`ffmpeg -ss <t> -i <src> -frames:v 1 f.png`).
   Anything showing a customer's name, paperwork, a tag, a plate or a VIN gets a `blur` box on
   that segment (see the cutter skill). If you can't blur it cleanly, drop the shot and tell Wells.
4. Run `python3 -m pipeline.visuals --job <job> --target <target>`.
5. Check frames at the hook, a callout, a zoomed piece and the end card. Captions must stay inside
   the frame and clear of the Instagram buttons (bottom 20% and right edge).
6. Mark the stage done and tell Wells what changed.

## What the renderer adds
- Captions: 3 words at a time, Anton, the spoken word in yellow `#FFC400`, slightly larger.
- Callouts: a yellow tag the first time a part from `style.json` is named.
- Punch-in zoom (108%) on every other talking piece, to hide jump cuts. Set `zoom` on a segment
  to override (1.0 = wide).
- Grade: a touch more contrast and warmth. End card for the last 1.6 s.

Change the look in `style.json`, not in code. Fonts live in `pipeline/fonts/` (OFL licensed).
