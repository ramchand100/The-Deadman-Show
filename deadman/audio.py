"""Voice an episode: one text-to-speech file per transcript line, joined into the episode audio.

Each line's audio is cached under a hash of its text, voice and settings, so after editing
the transcript only the changed lines are re-voiced (and paid for). Output, in the episode
folder:

    audio/segments/NNNN-<hash>.mp3   one file per line (the avatar tool's input)
    audio/episode.mp3                cold open + full episode
    audio/timings.json               exact start/end of every line, for video and timestamps
    captions.srt                     subtitles for YouTube
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tomllib
import wave
from dataclasses import dataclass
from pathlib import Path

import requests

from .figures import Figure
from .script import WORDS_PER_MINUTE, Episode, Segment

REPO = Path(__file__).resolve().parent.parent
STUDIO_FILE = REPO / "show" / "studio.toml"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
SAMPLE_RATE = 44100
CAPTION_WORDS = 9


class AudioError(RuntimeError):
    pass


def load_studio(path: Path = STUDIO_FILE) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


@dataclass
class Voice:
    voice_id: str
    settings: dict

    def key(self, text: str, model_id: str) -> str:
        blob = json.dumps([text, self.voice_id, model_id, self.settings], sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]


def voices_for(figure: Figure, studio: dict) -> dict[str, Voice]:
    tts = figure.tts
    settings = {k: tts[k] for k in ("stability", "similarity_boost", "style", "speed") if k in tts}
    return {
        "HOST": Voice(studio["host"].get("voice_id", ""), studio["host"].get("voice_settings", {})),
        "GUEST": Voice(tts.get("voice_id", ""), settings),
    }


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioError(f"{cmd[0]} failed: {result.stderr.strip()[-500:]}")


def _to_wav(src: Path, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", str(SAMPLE_RATE), "-ac", "1", str(dst)])


def _silence(seconds: float, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
          f"anullsrc=r={SAMPLE_RATE}:cl=mono", "-t", f"{seconds:.3f}", str(dst)])


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


class ElevenLabs:
    """Real voices. Needs ELEVENLABS_API_KEY and a voice id for both speakers."""

    suffix = ".mp3"

    def __init__(self, model_id: str, output_format: str, api_key: str | None = None):
        self.model_id, self.output_format = model_id, output_format
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        if not self.api_key:
            raise AudioError("Set ELEVENLABS_API_KEY to your ElevenLabs API key.")

    def synthesize(self, text: str, voice: Voice, previous_text: str, next_text: str, dst: Path) -> None:
        response = requests.post(
            ELEVENLABS_URL.format(voice_id=voice.voice_id),
            params={"output_format": self.output_format},
            headers={"xi-api-key": self.api_key},
            json={
                "text": text,
                "model_id": self.model_id,
                "voice_settings": voice.settings or None,
                # Neighbouring lines keep intonation natural across turns.
                "previous_text": previous_text or None,
                "next_text": next_text or None,
            },
            timeout=120,
        )
        if response.status_code != 200:
            raise AudioError(f"ElevenLabs error {response.status_code}: {response.text[:300]}")
        dst.write_bytes(response.content)


class Placeholder:
    """Silent audio timed like speech, so video can be built and tested before any voices exist."""

    suffix = ".wav"
    model_id = "placeholder"

    def synthesize(self, text: str, voice: Voice, previous_text: str, next_text: str, dst: Path) -> None:
        _silence(max(1.0, len(text.split()) / WORDS_PER_MINUTE * 60), dst)


def _playlist(ep: Episode) -> list[tuple[int, bool]]:
    """(segment index, is_cold_open) in playback order: the cold open first, then the episode."""
    order = []
    if ep.packaging:
        order += [(i, True) for i in range(ep.packaging.cold_open_start, ep.packaging.cold_open_end + 1)]
    order += [(i, False) for i in range(len(ep.segments))]
    return order


def estimate(ep: Episode, folder: Path, voices: dict[str, Voice], model_id: str) -> dict:
    """Characters to voice in total, and how many are new (not yet cached)."""
    seg_dir = folder / "audio" / "segments"
    total = new = 0
    for i, seg in enumerate(ep.segments):
        total += len(seg.text)
        key = voices[seg.speaker].key(seg.text, model_id)
        if not list(seg_dir.glob(f"{i + 1:04d}-{key}.*")):
            new += len(seg.text)
    return {"lines": len(ep.segments), "characters": total, "new_characters": new}


def _chapter_of(ep: Episode) -> list[str]:
    return [ch.title for ch in ep.chapters for _ in ch.segments]


def build_audio(ep: Episode, folder: Path, engine, voices: dict[str, Voice], studio: dict, log=print) -> dict:
    if engine.model_id != "placeholder":
        missing = [who for who, v in voices.items() if not v.voice_id]
        if missing:
            where = {"HOST": "show/studio.toml [host] voice_id",
                     "GUEST": f"figures/{ep.figure.slug}.toml [tts] voice_id"}
            raise AudioError("No ElevenLabs voice id for " + ", ".join(where[m] for m in missing))
    if not shutil.which("ffmpeg"):
        raise AudioError("ffmpeg is required (https://ffmpeg.org/download.html).")

    audio_dir = folder / "audio"
    seg_dir, wav_dir = audio_dir / "segments", audio_dir / "wav"
    seg_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(exist_ok=True)

    segments = ep.segments
    files: list[Path] = []
    for i, seg in enumerate(segments):
        voice = voices[seg.speaker]
        name = f"{i + 1:04d}-{voice.key(seg.text, engine.model_id)}"
        src = seg_dir / f"{name}{engine.suffix}"
        if not src.exists():
            for stale in seg_dir.glob(f"{i + 1:04d}-*"):
                stale.unlink()
            log(f"  voicing line {i + 1}/{len(segments)} ({seg.speaker.lower()})")
            prev_text = segments[i - 1].text if i else ""
            next_text = segments[i + 1].text if i + 1 < len(segments) else ""
            engine.synthesize(seg.text, voice, prev_text, next_text, src)
        wav = wav_dir / f"{name}.wav"
        if not wav.exists():
            _to_wav(src, wav)
        files.append(wav)

    gaps = studio.get("audio", {})
    turn_gap, chapter_gap = wav_dir / "gap-turn.wav", wav_dir / "gap-chapter.wav"
    _silence(gaps.get("pause_between_turns", 0.35), turn_gap)
    _silence(gaps.get("pause_between_chapters", 1.0), chapter_gap)
    chapter_titles = _chapter_of(ep)

    entries, concat, clock = [], [], 0.0
    playlist = _playlist(ep)
    for n, (i, cold) in enumerate(playlist):
        duration = wav_seconds(files[i])
        entries.append({
            "segment": i, "speaker": segments[i].speaker, "chapter": "Cold open" if cold else chapter_titles[i],
            "cold_open": cold, "start": round(clock, 3), "end": round(clock + duration, 3),
            "text_sha": hashlib.sha1(segments[i].text.encode()).hexdigest()[:12],
        })
        concat.append(files[i])
        clock += duration
        if n + 1 < len(playlist):
            nxt, next_cold = playlist[n + 1]
            gap = chapter_gap if (cold and not next_cold) or (not cold and chapter_titles[nxt] != chapter_titles[i]) \
                else turn_gap
            concat.append(gap)
            clock += wav_seconds(gap)

    listing = audio_dir / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in concat), encoding="utf-8")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
          "-ar", str(SAMPLE_RATE), "-ac", "1", "-b:a", "128k", str(audio_dir / "episode.mp3")])

    timings = {"engine": engine.model_id, "duration": round(clock, 3), "lines": entries}
    (audio_dir / "timings.json").write_text(json.dumps(timings, indent=1), encoding="utf-8")
    (folder / "captions.srt").write_text(to_srt(segments, entries), encoding="utf-8")
    return timings


def _srt_time(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list[Segment], entries: list[dict]) -> str:
    """Captions in short chunks, timed across each line in proportion to their length."""
    cues = []
    for e in entries:
        words = segments[e["segment"]].text.split()
        chunks = [words[k:k + CAPTION_WORDS] for k in range(0, len(words), CAPTION_WORDS)]
        total = sum(len(" ".join(c)) for c in chunks) or 1
        t = e["start"]
        for chunk in chunks:
            text = " ".join(chunk)
            dt = (e["end"] - e["start"]) * len(text) / total
            cues.append((t, t + dt, text))
            t += dt
    return "\n".join(f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n" for n, (a, b, text) in enumerate(cues, 1))


def load_timings(folder: Path, ep: Episode) -> dict | None:
    """Timings from the last `deadman audio` run, or None if the transcript changed since."""
    path = folder / "audio" / "timings.json"
    if not path.exists():
        return None
    timings = json.loads(path.read_text(encoding="utf-8"))
    segments = ep.segments
    if sum(not e["cold_open"] for e in timings["lines"]) != len(segments):
        return None
    for e in timings["lines"]:
        i = e["segment"]
        if i >= len(segments) or hashlib.sha1(segments[i].text.encode()).hexdigest()[:12] != e["text_sha"]:
            return None
    return timings
