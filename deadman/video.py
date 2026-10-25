"""Assemble an episode video in the fixed studio. Only the guest's portrait and avatar change.

For each line (in audio/timings.json order) the editor picks a shot: a close-up of the
speaker, or the wide two-shot at chapter starts, for short reactions and every few turns.
The speaker comes from their avatar clip, video/avatars/NNNN.mp4 (made by the avatar tool
from audio/segments/NNNN-*.mp3, on a green screen), or their still portrait if there is no
clip yet. Everything is keyed onto the same studio plate, with name cards, chapter cards
and the show's corner logo, then joined and laid under the episode audio.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PIL.PngImagePlugin import PngInfo

from .audio import REPO
from .script import Episode


class VideoError(RuntimeError):
    pass


def _path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else REPO / path


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoError(f"ffmpeg failed: {result.stderr.strip()[-800:]}")


def _hex(color: str) -> str:
    return color.replace("0x", "#")


@dataclass
class Shot:
    kind: str           # "closeup" or "wide"
    speaker: str        # "HOST" or "GUEST"
    lower_third: bool
    chapter_card: str   # chapter title to show, or ""


def plan_shots(ep: Episode, timings: dict, studio: dict) -> list[Shot]:
    """The edit: one shot per line of the timings, following the studio's rhythm rules."""
    rules = studio["shots"]
    segments = ep.segments
    shots, changes, seen_in_chapter, last = [], 0, set(), None
    for line in timings["lines"]:
        seg = segments[line["segment"]]
        chapter = line["chapter"]
        new_chapter = last is None or chapter != last["chapter"]
        if new_chapter:
            seen_in_chapter = set()
        if last is not None and seg.speaker != segments[last["segment"]].speaker:
            changes += 1
        wide = (new_chapter and not line["cold_open"]) or len(seg.text.split()) < rules["wide_if_words_under"] \
            or (changes and changes % rules["wide_every"] == 0 and seg.speaker == "HOST")
        shots.append(Shot(
            kind="wide" if wide else "closeup",
            speaker=seg.speaker,
            lower_third=not line["cold_open"] and seg.speaker not in seen_in_chapter,
            chapter_card=chapter if new_chapter and not line["cold_open"] else "",
        ))
        seen_in_chapter.add(seg.speaker)
        last = line
    return shots


def _keyed(stream: str, height: int, studio: dict, label: str) -> str:
    a = studio["avatar"]
    return (f"[{stream}]chromakey={a['key_color']}:{a['key_similarity']}:{a['key_blend']},"
            f"scale=-2:{height}[{label}]")


def _overlays(shot: Shot, ep: Episode, studio: dict, text_dir: Path, scale: float) -> list[str]:
    """drawbox/drawtext filters for the corner logo, name card and chapter card."""
    b, c = studio["brand"], studio["canvas"]
    w, h = int(c["width"] * scale), int(c["height"] * scale)
    font, serif = _path(b["font"]), _path(b["font_serif"])
    s = lambda v: int(v * scale)

    def text_file(name: str, text: str) -> Path:
        path = text_dir / f"{hashlib.sha1(text.encode()).hexdigest()[:10]}-{name}.txt"
        path.write_text(text, encoding="utf-8")
        return path

    filters = [f"drawtext=fontfile='{font}':textfile='{text_file('logo', b['show_name'])}':"
               f"fontsize={s(26)}:fontcolor={b['text']}@0.8:x={s(44)}:y={s(38)}"]
    if shot.lower_third:
        host = studio["host"]
        name, title = ((host["name"], host.get("title", "Host")) if shot.speaker == "HOST"
                       else (ep.figure.name, ep.figure.look.get("title", f"{ep.figure.born}-{ep.figure.died}")))
        x = s(80) if shot.speaker == "HOST" else w - s(860)
        y, until = h - s(260), b["lower_third_seconds"]
        on = f"enable='lt(t,{until})'"
        filters += [
            f"drawbox=x={x}:y={y}:w={s(780)}:h={s(150)}:color={b['panel']}@0.88:t=fill:{on}",
            f"drawbox=x={x}:y={y}:w={s(10)}:h={s(150)}:color={b['accent']}:t=fill:{on}",
            f"drawtext=fontfile='{font}':textfile='{text_file('name', name)}':fontsize={s(54)}:"
            f"fontcolor={b['text']}:x={x + s(40)}:y={y + s(22)}:{on}",
            f"drawtext=fontfile='{font}':textfile='{text_file('title', title)}':fontsize={s(30)}:"
            f"fontcolor={b['accent']}:x={x + s(40)}:y={y + s(92)}:{on}",
        ]
    if shot.chapter_card:
        on = f"enable='lt(t,{b['chapter_card_seconds']})'"
        filters += [
            f"drawbox=x=0:y={h // 2 - s(95)}:w={w}:h={s(190)}:color={b['panel']}@0.82:t=fill:{on}",
            f"drawbox=x={w // 2 - s(60)}:y={h // 2 - s(70)}:w={s(120)}:h={s(4)}:color={b['accent']}:t=fill:{on}",
            f"drawtext=fontfile='{serif}':textfile='{text_file('chapter', shot.chapter_card)}':"
            f"fontsize={s(64)}:fontcolor={b['text']}:x=(w-text_w)/2:y={h // 2 - s(30)}:{on}",
        ]
    return filters


def _blurred_plate(studio: dict, work: Path, scale: float) -> Path:
    """The studio plate, softened for close-ups. Made once and reused."""
    c, sh = studio["canvas"], studio["shots"]
    plate = _path(studio["set"]["plate"])
    dst = work / f"plate-blur-{scale}-{int(plate.stat().st_mtime)}.png"
    if not dst.exists():
        img = Image.open(plate).convert("RGB").resize((int(c["width"] * scale), int(c["height"] * scale)))
        img.filter(ImageFilter.GaussianBlur(sh["closeup_background_blur"] * scale)).save(dst)
    return dst


def _is_still(path: Path) -> bool:
    return path.suffix.lower() in (".png", ".jpg", ".jpeg")


def render_clip(shot: Shot, duration: float, sources: dict[str, Path], ep: Episode, studio: dict,
                dst: Path, work: Path, scale: float = 1.0, preset: str = "veryfast") -> None:
    """Render one line's shot. sources maps HOST/GUEST to an avatar clip (.mp4) or still portrait."""
    c, sh = studio["canvas"], studio["shots"]
    w, h = int(c["width"] * scale), int(c["height"] * scale)
    s = lambda v: int(v * scale)
    background = _blurred_plate(studio, work, scale) if shot.kind == "closeup" else _path(studio["set"]["plate"])
    inputs = ["-loop", "1", "-i", str(background)]

    def add(path: Path) -> int:
        """Add a still or a clip as an ffmpeg input and return its input index."""
        inputs.extend([*(["-loop", "1"] if _is_still(path) else ["-stream_loop", "-1"]), "-i", str(path)])
        return inputs.count("-i") - 1

    graph = [f"[0]scale={w}:{h}[bg]"]
    if shot.kind == "closeup":
        i = add(sources[shot.speaker])
        x = s(sh["closeup_host_x"] if shot.speaker == "HOST" else sh["closeup_guest_x"])
        graph += [_keyed(str(i), s(sh["closeup_height"]), studio, "fg"), f"[bg][fg]overlay=x={x}:y=H-h[base]"]
    else:
        ih, ig = add(sources["HOST"]), add(sources["GUEST"])
        graph += [_keyed(str(ih), s(sh["wide_height"]), studio, "host"),
                  _keyed(str(ig), s(sh["wide_height"]), studio, "guest"),
                  f"[bg][host]overlay=x={s(sh['wide_host_x'])}:y={s(sh['wide_y'])}[b1]",
                  f"[b1][guest]overlay=x={s(sh['wide_guest_x'])}:y={s(sh['wide_y'])}[base]"]
    overlays = ",".join(_overlays(shot, ep, studio, work, scale) + ["format=yuv420p"])
    encode = ["-t", f"{duration:.3f}", "-r", str(c["fps"]), "-an", "-c:v", "libx264", "-preset", preset, "-crf", "20"]

    used = [sources[shot.speaker]] if shot.kind == "closeup" else list(sources.values())
    if all(_is_still(p) for p in used):
        # Nothing moves but the text: compose the frame once, then encode it with the overlays.
        key = hashlib.sha1(";".join(graph + inputs).encode()).hexdigest()[:12]
        frame = work / f"frame-{key}.png"
        if not frame.exists():
            _run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(graph),
                  "-map", "[base]", "-frames:v", "1", str(frame)])
        _run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(frame), "-vf", overlays,
              "-tune", "stillimage", *encode, str(dst)])
    else:
        graph.append(f"[base]{overlays}[v]")
        _run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(graph),
              "-map", "[v]", "-tune", "film", *encode, str(dst)])


def _sources(folder: Path, segment: int, ep: Episode, studio: dict) -> dict[str, Path]:
    portraits = {"HOST": _path(studio["host"]["portrait"]), "GUEST": _path(ep.figure.look.get("portrait", ""))}
    for who, p in portraits.items():
        if not p.is_file():
            raise VideoError(f"Missing {who.lower()} portrait {p}. Add it (see show/studio.md) or run "
                             "`python -m deadman placeholders`.")
    speaker = ep.segments[segment].speaker
    clip = folder / "video" / "avatars" / f"{segment + 1:04d}.mp4"
    return {**portraits, speaker: clip} if clip.exists() else portraits


def build_video(ep: Episode, folder: Path, timings: dict, studio: dict, preview: int = 0,
                scale: float = 1.0, log=print) -> Path:
    if not _path(studio["set"]["plate"]).is_file():
        raise VideoError("Missing studio plate. Add assets/studio/plate.png (see show/studio.md) or run "
                         "`python -m deadman placeholders`.")
    lines = timings["lines"][:preview] if preview else timings["lines"]
    shots = plan_shots(ep, timings, studio)[: len(lines)]
    video_dir = folder / "video"
    clip_dir, work = video_dir / "clips", video_dir / "work"
    clip_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(exist_ok=True)
    preset = "ultrafast" if preview else "veryfast"

    clips = []
    for n, (line, shot) in enumerate(zip(lines, shots)):
        end = timings["lines"][n + 1]["start"] if n + 1 < len(timings["lines"]) else line["end"]
        duration = max(end - line["start"], 0.2)
        sources = _sources(folder, line["segment"], ep, studio)
        key = hashlib.sha1(json.dumps([shot.__dict__, round(duration, 3), scale, preset,
                                       {k: [str(v), v.stat().st_mtime] for k, v in sources.items()},
                                       studio], sort_keys=True, default=str).encode()).hexdigest()[:12]
        dst = clip_dir / f"{n:04d}-{key}.mp4"
        if not dst.exists():
            for stale in clip_dir.glob(f"{n:04d}-*"):
                stale.unlink()
            log(f"  shot {n + 1}/{len(lines)}: {shot.kind} {shot.speaker.lower()}")
            render_clip(shot, duration, sources, ep, studio, dst, work, scale, preset)
        clips.append(dst)

    listing = video_dir / "clips.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in clips), encoding="utf-8")
    out = video_dir / ("preview.mp4" if preview else "episode.mp4")
    cut_early = len(lines) < len(timings["lines"])
    total = timings["lines"][len(lines)]["start"] if cut_early else timings["duration"]
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
          "-i", str(folder / "audio" / "episode.mp3"), "-map", "0:v", "-map", "1:a",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}", str(out)])
    return out


# --- placeholders ---
# Placeholder images carry a PNG text tag, so the pipeline can warn while any are still in use.

PLACEHOLDER_TAG = ("deadman", "placeholder")


def is_placeholder(path: Path) -> bool:
    try:
        return Image.open(path).text.get(PLACEHOLDER_TAG[0]) == PLACEHOLDER_TAG[1]
    except (OSError, AttributeError):
        return False


def _save_placeholder(img: Image.Image, dst: Path) -> None:
    info = PngInfo()
    info.add_text(*PLACEHOLDER_TAG)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, pnginfo=info)


def placeholder_assets(ep: Episode, studio: dict) -> list[Path]:
    paths = [_path(studio["set"]["plate"]), _path(studio["host"]["portrait"]),
             _path(ep.figure.look.get("portrait", ""))]
    return [p for p in paths if p.is_file() and is_placeholder(p)]

def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def placeholder_plate(studio: dict, dst: Path) -> None:
    """A drawn stand-in for the studio plate, laid out like the real one will be."""
    b, c = studio["brand"], studio["canvas"]
    w, h = c["width"], c["height"]
    img = Image.new("RGB", (w, h), "#15191d")
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(h * 0.72), w, h], fill="#3a2a1e")                      # wood floor
    for x in range(40, int(w * 0.42), 46):                                     # bookshelves, left
        for row, y in enumerate(range(90, int(h * 0.70), 120)):
            shade = ["#5b3a26", "#7a4b2a", "#2f4a3a", "#6b2f2f", "#3b3f5c"][(x // 46 + row) % 5]
            d.rectangle([x, y, x + 34, y + 100], fill=shade)
        d.rectangle([x - 6, 80, x - 2, int(h * 0.70)], fill="#2a1d14")
    for x in range(int(w * 0.58), w - 40, 150):                                # acoustic panels, right
        for y in range(90, int(h * 0.68), 150):
            d.rounded_rectangle([x, y, x + 132, y + 132], radius=10, fill="#262b30")
    neon = _font(_path(b["font"]), 64)
    d.text((int(w * 0.79), 150), b["show_name"], font=neon, fill=_hex(b["accent"]), anchor="mm")
    for cx in (int(w * 0.27), int(w * 0.73)):                                  # two armchairs
        d.rounded_rectangle([cx - 190, int(h * 0.50), cx + 190, int(h * 0.86)], radius=60, fill="#6a4128")
        d.rounded_rectangle([cx - 150, int(h * 0.38), cx + 150, int(h * 0.62)], radius=50, fill="#7b4c2f")
    d.ellipse([w // 2 - 90, int(h * 0.66), w // 2 + 90, int(h * 0.74)], fill="#4a3324")   # table
    img = img.filter(ImageFilter.GaussianBlur(1.5))
    ImageDraw.Draw(img).text((w - 30, h - 24), "PLACEHOLDER STUDIO", font=_font(_path(b["font"]), 22),
                             fill="#9aa3a8", anchor="rs")
    _save_placeholder(img, dst)


def placeholder_portrait(name: str, facing: str, color: str, studio: dict, dst: Path) -> None:
    """A seated silhouette on green, facing the other chair, labelled with the person's name."""
    b = studio["brand"]
    w, h = 1000, 1080
    img = Image.new("RGB", (w, h), "#00ff00")
    d = ImageDraw.Draw(img)
    head_x = w // 2 + (-40 if facing == "left" else 40)
    d.rounded_rectangle([w // 2 - 330, 560, w // 2 + 330, h], radius=160, fill=color)    # shoulders
    d.ellipse([head_x - 165, 170, head_x + 165, 520], fill=color)                     # head
    nose_x = head_x - 175 if facing == "left" else head_x + 175
    d.polygon([(nose_x, 345), (head_x + (-150 if facing == "left" else 150), 315),
               (head_x + (-150 if facing == "left" else 150), 385)], fill=color)
    d.text((w // 2, 650), name, font=_font(_path(b["font"]), 64), fill="#f4ede1", anchor="mm")
    d.text((w // 2, 725), "placeholder", font=_font(_path(b["font"]), 40), fill="#d8d0c4", anchor="mm")
    _save_placeholder(img, dst)


def make_placeholders(ep_figure, studio: dict) -> list[Path]:
    """Create stand-ins for any missing studio assets. Never overwrites real ones."""
    made = []
    plate = _path(studio["set"]["plate"])
    if not plate.exists():
        placeholder_plate(studio, plate)
        made.append(plate)
    host = _path(studio["host"]["portrait"])
    if not host.exists():
        placeholder_portrait(studio["host"]["name"].upper(), "right", "#2d4d6a", studio, host)
        made.append(host)
    guest = _path(ep_figure.look.get("portrait", f"figures/assets/{ep_figure.slug}/portrait.png"))
    if not guest.exists():
        placeholder_portrait(ep_figure.name.upper(), "left", "#6a3d2d", studio, guest)
        made.append(guest)
    return made
