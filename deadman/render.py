"""Write an episode to disk as a readable script (Markdown), a YouTube description, and JSON."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from .script import WORDS_PER_MINUTE, Episode

def slugify(text: str, max_len: int = 50) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len].rstrip("-")


def _timestamp(words: int) -> str:
    seconds = round(words / WORDS_PER_MINUTE * 60)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapter_timestamps(ep: Episode) -> list[tuple[str, str]]:
    """Estimated start time of each chapter, from spoken word counts (cold open included)."""
    words = 0
    if ep.packaging:
        words = sum(len(s.text.split()) for s in _cold_open(ep))
    stamps = []
    for ch in ep.chapters:
        stamps.append((_timestamp(words), ch.title))
        words += sum(len(s.text.split()) for s in ch.segments)
    stamps[0] = ("0:00", stamps[0][1])
    return stamps


def _cold_open(ep: Episode):
    p = ep.packaging
    return ep.segments[p.cold_open_start: p.cold_open_end + 1] if p else []


def _words(ep: Episode, index: int, n: int = 8, last: bool = False) -> str:
    """The first (or last) few words of a segment, so a clip can be found in the script."""
    if not 0 <= index < len(ep.segments):
        return "?"
    words = ep.segments[index].text.split()
    return " ".join(words[-n:] if last else words[:n])


def _source_numbers(ep: Episode) -> dict[str, int]:
    cited = [c for seg in ep.segments for c in seg.citations if c in ep.passages]
    return {pid: n for n, pid in enumerate(dict.fromkeys(cited), 1)}


def _sources_list(ep: Episode, numbers: dict[str, int]) -> list[str]:
    lines = []
    for pid, n in numbers.items():
        p = ep.passages[pid]
        note = " (biography)" if p.kind == "biography" else ""
        lines.append(f"{n}. {p.citation()}{note} — passage `{pid}`")
    return lines


def to_markdown(ep: Episode, host_name: str = "Host") -> str:
    speakers = {"HOST": host_name.upper(), "GUEST": ep.figure.speaker_label}
    numbers = _source_numbers(ep)
    words = sum(len(s.text.split()) for s in ep.segments)

    def line(seg) -> str:
        refs = "".join(f"[{numbers[c]}]" for c in seg.citations if c in numbers)
        return f"**{speakers[seg.speaker]}:** {seg.text}{' ' + refs if refs else ''}"

    out = ["<!-- Generated from transcript.md by `deadman render`. Edit transcript.md, not this file. -->", "",
           f"# {ep.title}", "", f"*{ep.hook}*", "",
           f"Guest: {ep.figure.name} (AI recreation) · Host: {host_name} · "
           f"~{words:,} words, about {round(words / WORDS_PER_MINUTE)} minutes", ""]
    if ep.issues:
        out += [f"> **Review needed:** {len(ep.issues)} fact-check issue(s). See the end of this file.", ""]

    multi = len(ep.chapters) > 1
    if multi:
        out += ["## Chapters", ""] + [f"- {t} {title}" for t, title in chapter_timestamps(ep)] + [""]
    if ep.packaging:
        out += ["## Cold open", "", "*(Played before the intro.)*", ""]
        out += [x for seg in _cold_open(ep) for x in (line(seg), "")]

    out += ["## Script", ""]
    for ch in ep.chapters:
        if multi:
            out += [f"### {ch.title}", ""]
        out += [x for seg in ch.segments for x in (line(seg), "")]

    if p := ep.packaging:
        out += ["## YouTube packaging", "", "**Title options**", ""] + [f"- {t}" for t in p.title_options]
        out += ["", "**Thumbnail text**", ""] + [f"- {t}" for t in p.thumbnail_text]
        out += ["", "**Clips for Shorts**", ""]
        for c in p.clips:
            out.append(f"- **{c.title}**: {c.why}  \n  From \"{_words(ep, c.start_segment)}...\" "
                       f"to \"...{_words(ep, c.end_segment, last=True)}\"")
        out.append("")

    out += ["## Sources", ""] + _sources_list(ep, numbers) + [""]

    out += ["## Fact check", ""]
    if ep.fact_check_summary:
        out += [ep.fact_check_summary, ""]
    if not ep.issues:
        out.append("No issues flagged.")
    for issue in ep.issues:
        out += [f"- **Segment {issue.segment} · {issue.kind}:** \"{issue.excerpt}\"",
                f"  - {issue.explanation}",
                f"  - Fix: {issue.suggested_fix}"]
    return "\n".join(out) + "\n"


def youtube_description(ep: Episode) -> str:
    """Paste-ready description: summary, chapter timestamps and the sources."""
    numbers = _source_numbers(ep)
    out = [ep.packaging.description if ep.packaging else ep.hook, ""]
    if len(ep.chapters) > 1:
        out += ["Chapters:"] + [f"{t} {title}" for t, title in chapter_timestamps(ep)] + [""]
    out.append("Sources (public domain, via Project Gutenberg):")
    seen = []
    for pid in numbers:
        p = ep.passages[pid]
        work = f"{p.title} ({p.year})"
        if work not in seen:
            seen.append(work)
    out += [f"- {w}" for w in seen]
    out += ["", f"{ep.figure.name} in this video is an AI recreation, not the real person. The answers are "
            "generated, grounded in the writings and biography listed above."]
    return "\n".join(out) + "\n"


def to_json(ep: Episode) -> dict:
    return {
        "figure": ep.figure.slug,
        "topic": ep.topic,
        "title": ep.title,
        "hook": ep.hook,
        "chapters": [{"title": ch.title, "segments": [s.model_dump() for s in ch.segments]} for ch in ep.chapters],
        "packaging": ep.packaging.model_dump() if ep.packaging else None,
        "passages": {pid: asdict(p) for pid, p in ep.passages.items()},
        "fact_check": {
            "summary": ep.fact_check_summary,
            "issues": [i.model_dump() for i in ep.issues],
        },
    }


def save(ep: Episode, host_name: str, folder: Path) -> Path:
    """Write the generated files (script.md, youtube-description.txt, episode.json) into folder."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "script.md").write_text(to_markdown(ep, host_name), encoding="utf-8")
    (folder / "youtube-description.txt").write_text(youtube_description(ep), encoding="utf-8")
    (folder / "episode.json").write_text(json.dumps(to_json(ep), indent=2, ensure_ascii=False), encoding="utf-8")
    return folder
