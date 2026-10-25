import io
import wave

import pytest

from deadman import audio
from deadman.audio import ElevenLabs, Placeholder, Voice, build_audio, estimate, load_timings, to_srt
from deadman.figures import load_figure
from deadman.longform import Clip, Packaging
from deadman.script import Chapter, Episode, Segment

STUDIO = {"host": {"voice_id": "ram"}, "audio": {"pause_between_turns": 0.25, "pause_between_chapters": 0.5}}
VOICES = {"HOST": Voice("ram", {}), "GUEST": Voice("smith", {"stability": 0.5})}


def episode():
    seg = lambda who, text: Segment(speaker=who, text=text, citations=[])
    ep = Episode(figure=load_figure("adam_smith"), topic="", title="T", hook="", passages={}, chapters=[
        Chapter("One", [seg("HOST", "Welcome to the show today."), seg("GUEST", "Thank you, sir.")]),
        Chapter("Two", [seg("HOST", "Tell me about pins and needles."), seg("GUEST", "Pins are wonderful.")]),
    ])
    ep.packaging = Packaging(title_options=[], thumbnail_text=[], description="", cold_open_start=3,
                             cold_open_end=3, clips=[Clip(start_segment=0, end_segment=1, title="c", why="")])
    return ep


class CountingPlaceholder(Placeholder):
    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice, previous_text, next_text, dst):
        self.calls.append(text)
        super().synthesize(text, voice, previous_text, next_text, dst)


def test_build_audio_times_lines_and_reuses_unchanged_ones(tmp_path):
    ep = episode()
    engine = CountingPlaceholder()
    timings = build_audio(ep, tmp_path, engine, VOICES, STUDIO, log=lambda *_: None)

    lines = timings["lines"]
    assert [(l["segment"], l["cold_open"]) for l in lines] == [(3, True), (0, False), (1, False), (2, False), (3, False)]
    assert lines[0]["start"] == 0 and lines[1]["chapter"] == "One" and lines[3]["chapter"] == "Two"
    # Cold open -> episode and chapter One -> Two get the longer pause.
    assert lines[1]["start"] - lines[0]["end"] == pytest.approx(0.5, abs=0.01)
    assert lines[2]["start"] - lines[1]["end"] == pytest.approx(0.25, abs=0.01)
    assert lines[3]["start"] - lines[2]["end"] == pytest.approx(0.5, abs=0.01)
    assert (tmp_path / "audio" / "episode.mp3").exists() and (tmp_path / "captions.srt").exists()
    assert len(engine.calls) == 4

    # Edit one line: only that line is voiced again, and old timings no longer match.
    ep.chapters[1].segments[1].text = "Pins are truly wonderful things."
    assert load_timings(tmp_path, ep) is None
    assert estimate(ep, tmp_path, VOICES, "placeholder")["new_characters"] == len("Pins are truly wonderful things.")
    engine.calls.clear()
    build_audio(ep, tmp_path, engine, VOICES, STUDIO, log=lambda *_: None)
    assert engine.calls == ["Pins are truly wonderful things."]
    assert load_timings(tmp_path, ep) is not None


def test_missing_voice_id_is_reported_before_spending(tmp_path):
    with pytest.raises(audio.AudioError, match=r"\[tts\] voice_id"):
        build_audio(episode(), tmp_path, ElevenLabs("m", "mp3_44100_128", api_key="k"),
                    {"HOST": Voice("ram", {}), "GUEST": Voice("", {})}, STUDIO)


def test_elevenlabs_request(monkeypatch, tmp_path):
    sent = {}

    def fake_post(url, params, headers, json, timeout):
        sent.update(url=url, params=params, headers=headers, json=json)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(44100), w.writeframes(b"\0\0" * 4410)
        return type("R", (), {"status_code": 200, "content": buf.getvalue(), "text": ""})()

    monkeypatch.setattr(audio.requests, "post", fake_post)
    ElevenLabs("eleven_multilingual_v2", "mp3_44100_128", api_key="secret").synthesize(
        "Hello.", Voice("smith", {"stability": 0.5}), "Before.", "", tmp_path / "x.mp3")
    assert sent["url"].endswith("/v1/text-to-speech/smith")
    assert sent["params"] == {"output_format": "mp3_44100_128"} and sent["headers"] == {"xi-api-key": "secret"}
    assert sent["json"] == {"text": "Hello.", "model_id": "eleven_multilingual_v2",
                            "voice_settings": {"stability": 0.5}, "previous_text": "Before.", "next_text": None}


def test_srt_splits_long_lines_into_timed_chunks():
    segs = [Segment(speaker="HOST", text=" ".join(f"w{i}" for i in range(20)), citations=[])]
    srt = to_srt(segs, [{"segment": 0, "start": 0.0, "end": 10.0}])
    assert srt.count(" --> ") == 3 and "00:00:00,000 --> " in srt and srt.rstrip().endswith("w18 w19")
