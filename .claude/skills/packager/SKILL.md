---
name: packager
description: Make the cover, titles, captions and hashtags for a finished cut and the approval card Wells signs off on. Use after the audio stage; never posts.
---

# Packager (stage 4)

You package a finished cut for each platform and hand Wells an approval card. You never post,
schedule or upload anything; posting is a separate step after Wells approves the exact video,
caption and account.

## Steps
1. **Read what works**: `python3 -c "from pipeline import trends; import json; print(json.dumps(trends.captions(), indent=1))"`
   gives his top captions by plays, how many reels used hashtags, and the median caption length.
   Also read `trends.plan_moves` in the job.
2. **Write the copy** into `job.json` → `package.<target>`:
   - `cover_text`: 2-5 words, usually the hook title (`\N` for a line break).
   - `copy.<platform>`: `caption`, `hashtags` (list), and `title` for YouTube. Platforms per target
     are in `pipeline/package.json`.
   - Write like Wells: short, plain, his own phrases ("Customer states…"). Don't give the answer
     away in the caption if the video has a reveal; a question can pull comments (his weakest number).
   - Hashtags: 0-5 niche ones. YouTube Shorts need `#Shorts`.
   - Never a customer's name, the employer's name, a plate, a VIN or a phone number.
3. Run `python3 -m pipeline.package --job <job> --target <target> [--cover-at <s>]`. It picks the
   sharpest clean frame in the first 8 s (or `--cover-at`), keeps privacy blur, adds the cover text,
   checks limits and privacy patterns, and writes `out/<target>-approval.md` and `job.approval.items`.
4. **Look at the cover** and at frames of the final video for anything private the earlier
   stages missed (tags, paperwork, plates). Fix with a `blur` box on the segment and re-run
   visuals → audio → package.
5. Show Wells the card: the final video, the cover, each account with its exact caption. Ask which
   accounts to approve. Record his answer in `job.approval` (`approved`, `by`, `at`, per-item
   `approved`). Each item pins the video's sha256; if the video changes, the card must be re-made
   and re-approved.
