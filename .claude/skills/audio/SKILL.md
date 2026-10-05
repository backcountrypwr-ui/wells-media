---
name: audio
description: Clean up Wells's voice, add a royalty-free music bed under it, and set platform loudness on a styled cut. Use after the visuals stage, before the packager.
---

# Audio (stage 3)

You take `jobs/<job>/out/<target>-visuals.mp4` (or the rough cut) and fix the sound. You don't
change the picture, the cut or the captions, and you never post anything.

## Steps
1. **Music**: use a track from `pipeline/music/` (see its README). Only original, royalty-free
   music: no commercial songs, since Instagram and YouTube mute or flag them. For a new track,
   `vidiq_generate_music` costs 25 vidIQ credits per track; check `vidiq_balance` first, describe
   genre, mood, instruments and tempo, and end the prompt with "instrumental". Save it as
   `.m4a` in `pipeline/music/` and add a README row with the prompt. Pick the track per job with
   `audio.<target>.music`, or pass `--music`; `--no-music` for voice only.
2. Run `python3 -m pipeline.audio --job <job> --target <target>`. It prints the final loudness.
3. **Check**: loudness within 1 dB of `style.json` `audio.lufs` (-14) and peak at or under
   -1.5 dBTP; audio and video the same length. Compare levels in a pause and in talking
   (`ffmpeg -ss <t> -t <s> -i <file> -af volumedetect -f null -`): the voice must clearly sit on
   top. If the music fights the voice, raise `music_under_db` for that job.
4. Set `stages.audio` done (the script does) and tell Wells which track you used and how it sounds.

## Settings (`style.json` → `audio`)
- `lufs` -14 and `true_peak` -2 (AAC encoding adds about 0.5 dB, landing near -1.5).
- `music_under_db` 20: the bed's loudness below the voice; `duck_ratio` 4 dips it further while talking.
- Voice chain: 80 Hz high-pass (rumble, wind), FFT denoise, 3:1 compression.
