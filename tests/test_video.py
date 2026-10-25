import subprocess

from deadman.audio import Placeholder, build_audio, load_studio
from deadman.video import build_video, make_placeholders, placeholder_assets, plan_shots
from tests.test_audio import STUDIO, VOICES, episode


def test_plan_shots_follows_the_studio_rhythm():
    ep = episode()
    timings = {"lines": [
        {"segment": 3, "chapter": "Cold open", "cold_open": True},
        {"segment": 0, "chapter": "One", "cold_open": False},
        {"segment": 1, "chapter": "One", "cold_open": False},
        {"segment": 2, "chapter": "Two", "cold_open": False},
        {"segment": 3, "chapter": "Two", "cold_open": False},
    ]}
    studio = {"shots": {"wide_if_words_under": 3, "wide_every": 99}}
    shots = plan_shots(ep, timings, studio)
    # Cold open: no cards. Chapter starts: wide with a chapter card. Otherwise a close-up.
    assert [(s.kind, s.speaker, s.lower_third, s.chapter_card) for s in shots] == [
        ("closeup", "GUEST", False, ""),
        ("wide", "HOST", True, "One"),
        ("closeup", "GUEST", True, ""),
        ("wide", "HOST", True, "Two"),
        ("closeup", "GUEST", True, ""),
    ]
    # Short reactions ("Thank you, sir." is 3 words) cut to the wide shot.
    short = plan_shots(ep, timings, {"shots": {"wide_if_words_under": 4, "wide_every": 99}})
    assert short[2].kind == "wide"


def test_build_video_end_to_end_with_stills_and_an_avatar_clip(tmp_path):
    studio = load_studio()
    studio["set"]["plate"] = str(tmp_path / "plate.png")
    studio["host"]["portrait"] = str(tmp_path / "ram.png")
    ep = episode()
    ep.figure.look["portrait"] = str(tmp_path / "smith.png")
    make_placeholders(ep.figure, studio)
    assert len(placeholder_assets(ep, studio)) == 3

    timings = build_audio(ep, tmp_path, Placeholder(), VOICES, {**STUDIO, **studio}, log=lambda *_: None)
    # The avatar tool's output for line 2 (Smith): a short green-screen clip.
    avatars = tmp_path / "video" / "avatars"
    avatars.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x00FF00:s=320x240:d=1",
                    "-vf", "drawbox=x=100:y=60:w=120:h=120:color=red:t=fill", str(avatars / "0002.mp4")], check=True)

    out = build_video(ep, tmp_path, timings, studio, scale=0.25, log=lambda *_: None)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout
    assert "480" in probe and "audio" in probe
    duration = float(probe.strip().splitlines()[-1])
    assert abs(duration - timings["duration"]) < 0.5
