# Studio setup

The studio is built once and never changes. Each new guest needs only a portrait and a
voice. Settings live in `show/studio.toml`; each guest's look and voice are in the `[look]`
and `[tts]` sections of `figures/<slug>.toml`.

Until the real assets exist, `python -m deadman placeholders` creates labelled stand-ins so
the whole pipeline can run.

## Composition rules (all assets)

- 16:9, 1920x1080.
- **Host (Ram) sits in the LEFT chair, facing right. The guest sits in the RIGHT chair,
  facing left.** Every portrait and avatar must follow this, or the cuts look wrong.
- Lighting everywhere: warm tungsten key light, soft teal rim light from behind.
- Avatars and portraits are made on a **pure green (#00FF00) background**. The pipeline keys
  them onto the same studio plate, so the set is identical in every episode.

## 1. The studio plate (once)

Generate with any good image model, then save as `assets/studio/plate.png` (1920x1080).
Generate several and pick one; this image is the show's identity.

> Wide shot of an intimate podcast studio, 16:9, photoreal, cinematic, no people. Two worn
> brown leather armchairs angled toward each other on a dark wood floor, the left chair on
> the left third of the frame and the right chair on the right third. Between them a small
> round walnut table with two glasses of water. Two black broadcast microphones on boom arms
> reaching toward each chair. Behind the left chair, floor-to-ceiling shelves of old
> leather-bound books and a brass reading lamp. Behind the right chair, dark charcoal
> acoustic panels and a softly glowing teal neon sign reading "THE DEADMAN SHOW". Warm
> tungsten light, deep teal accents, shallow depth of field, slightly moody.

## 2. Ram (once)

Ram appears with his real face and voice, so both come from recordings of Ram, made with
his consent.

**Voice (ElevenLabs):** create a Professional Voice Clone from clean recordings of Ram
speaking naturally (ElevenLabs recommends substantially more audio for a Professional clone
than for an Instant one; a quiet room and a decent USB microphone matter more than length).
Read some of his own lines from `episodes/002-adam-smith-longform/transcript.md` so the
clone learns the show's tone. Put the voice id in `show/studio.toml` under `[host]
voice_id`.

**Avatar:** with the avatar tool you choose, create a digital twin from a few minutes of
video of Ram, recorded on a green screen, framed from the knees up, seated, facing slightly
to his left (camera right) as if talking to the guest. Also export one still as
`assets/host/portrait.png` (green background), used in the wide shot and in previews.

## 3. Each new guest

1. **Portrait:** use the `[look] prompt` from the guest's figure file with an image model,
   giving it the listed public-domain reference portraits. Check the likeness against the
   references. Save as the `[look] portrait` path (green background, facing left).
2. **Voice:** in ElevenLabs Voice Design, paste the `[tts] description`, generate options,
   listen to a long guest line from the transcript, and keep the best. Never clone a
   real living person's voice for a guest. Put the voice id in `[tts] voice_id`.
3. **Avatar:** in the avatar tool, create the guest's avatar from the portrait.

## 4. Producing an episode

```bash
python -m deadman audio 2 --estimate     # character count, before spending credits
python -m deadman audio 2                # ElevenLabs voices; only changed lines are re-made
python -m deadman video 2 --preview 12   # first 12 lines, quick check of the edit
python -m deadman video 2                # the full episode
```

`audio` writes `audio/episode.mp3`, `audio/timings.json` (exact start and end of every
line) and `captions.srt` (upload to YouTube). With timings, `render` replaces the estimated
chapter timestamps with exact ones.

`video` uses, for each line, the avatar clip at `video/avatars/NNNN.mp4` if it exists
(made by the avatar tool from that line's audio in `audio/segments/`), and otherwise the
speaker's still portrait. Audio and video files are not committed to git.
