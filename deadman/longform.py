"""Long-form episodes: a chaptered conversation written one chapter at a time, then packaged for YouTube."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import anthropic
from pydantic import BaseModel

from .figures import Figure
from .retrieval import BM25Index
from .script import (
    WORDS_PER_MINUTE,
    Chapter,
    Episode,
    PlannedQuestion,
    Segment,
    _call,
    _format_passages,
    fact_check,
    format_transcript,
    gather_passages,
    mechanical_checks,
    persona_prompt,
)
from .sources import Passage

FORMATS_DIR = Path(__file__).resolve().parent.parent / "formats"
# Recent lines from the previous chapter, so each chapter picks up where the last left off.
HANDOFF_SEGMENTS = 4


@dataclass(frozen=True)
class FormatChapter:
    id: str
    title: str
    minutes: int
    goal: str
    beats: list[str]


@dataclass(frozen=True)
class ShowFormat:
    name: str
    description: str
    style: str
    tradition: str
    chapters: list[FormatChapter]

    @property
    def minutes(self) -> int:
        return sum(c.minutes for c in self.chapters)


def load_format(name: str, formats_dir: Path = FORMATS_DIR) -> ShowFormat:
    path = formats_dir / f"{name}.toml"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in formats_dir.glob("*.toml")))
        raise FileNotFoundError(f"No format {name!r}. Available: {available}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    chapters = [FormatChapter(**c) for c in data.pop("chapters")]
    return ShowFormat(
        name=data["name"], description=data["description"], style=data["style"].strip(),
        tradition=data.get("tradition", "").strip(), chapters=chapters,
    )


class ChapterPlan(BaseModel):
    title: str
    questions: list[PlannedQuestion]


class LongformPlan(BaseModel):
    title: str
    hook: str
    chapters: list[ChapterPlan]


class ChapterScript(BaseModel):
    segments: list[Segment]


class Clip(BaseModel):
    start_segment: int
    end_segment: int
    title: str
    why: str


class Packaging(BaseModel):
    title_options: list[str]
    thumbnail_text: list[str]
    description: str
    cold_open_start: int
    cold_open_end: int
    clips: list[Clip]


def _outline(fmt: ShowFormat, plan: LongformPlan) -> str:
    lines = []
    for i, (spec, ch) in enumerate(zip(fmt.chapters, plan.chapters), 1):
        lines.append(f"{i}. {ch.title} ({spec.minutes} min): {spec.goal}")
        lines += [f"   - {q.question}" for q in ch.questions]
    return "\n".join(lines)


def plan_longform(
    client: anthropic.Anthropic, figure: Figure, fmt: ShowFormat, themes: str, host_name: str
) -> LongformPlan:
    chapters = "\n".join(
        f"{i}. {c.title} ({c.minutes} min). Goal: {c.goal}\n" + "\n".join(f"   - {b}" for b in c.beats)
        for i, c in enumerate(fmt.chapters, 1)
    )
    user = f"""Plan a long-form episode (about {fmt.minutes} minutes) with {figure.name}. \
The host is {host_name}.

{fmt.style}

Running order (keep exactly these {len(fmt.chapters)} chapters, in this order; you may give \
each a catchier title that fits this guest):
{chapters}

{f"Themes the host especially wants to cover: {themes}" if themes else ""}

For each chapter, write 3-6 host questions that are specific to {figure.name}'s life and \
work, the kind a well-prepared interviewer asks. For each question, give 3-6 search terms \
that would find relevant passages in the guest's writings or biography, written in the \
guest's own period vocabulary and spelling. Also give the episode a title and a \
one-sentence hook."""
    return _call(client, persona_prompt(figure), user, LongformPlan, effort="medium")


def write_chapter(
    client: anthropic.Anthropic,
    figure: Figure,
    fmt: ShowFormat,
    plan: LongformPlan,
    index: int,
    passages: dict[str, Passage],
    previous: list[Segment],
    quoted_before: set[str],
    host_name: str,
) -> ChapterScript:
    spec, chapter = fmt.chapters[index], plan.chapters[index]
    questions = "\n".join(f"- {q.question}" for q in chapter.questions)
    handoff = format_transcript(previous[-HANDOFF_SEGMENTS:]) if previous else "(This is the first chapter.)"
    position = "first" if index == 0 else "last" if index == len(fmt.chapters) - 1 else "next"
    user = f"""Write the {position} chapter of this episode.

Episode: {plan.title}
Host name: {host_name}

{fmt.style}
{fmt.tradition}

Full running order, for context:
{_outline(fmt, plan)}

This chapter: "{chapter.title}"
Goal: {spec.goal}
Target length: about {spec.minutes * WORDS_PER_MINUTE} words.
Questions to cover, with natural follow-ups (reorder or merge them if the conversation flows better):
{questions}

How the previous chapter ended (continue smoothly from here; do not greet again or recap):
{handoff}

Passages already quoted earlier in the episode (do not quote them again): \
{", ".join(sorted(quoted_before)) or "none"}

Source passages for this chapter (cite them by id):

{_format_passages(passages)}"""
    return _call(client, persona_prompt(figure), user, ChapterScript, effort="high")


def package(client: anthropic.Anthropic, figure: Figure, episode: Episode, host_name: str) -> Packaging:
    system = """You package long-form podcast episodes for YouTube. You write titles and \
descriptions that are compelling but honest: no claims the episode does not deliver, and the \
guest is always identified as an AI recreation."""
    chapters = "\n".join(f"- {ch.title}" for ch in episode.chapters)
    user = f"""Package this episode of The Deadman Show, hosted by {host_name}, with an AI \
recreation of {figure.name}.

Give:
- title_options: 5 YouTube titles, under 70 characters.
- thumbnail_text: 3 options of 2-5 words each.
- description: 2 short paragraphs saying what the episode covers, ending with a sentence \
that the guest is an AI recreation built from {figure.name}'s writings and a public-domain \
biography. Chapter timestamps and sources are added automatically; do not write them.
- cold_open_start / cold_open_end: the segment range (inclusive, 1-4 segments) that would \
make the most gripping 20-40 second cold open before the intro.
- clips: 5-8 self-contained moments for Shorts, each 2-8 segments, with a hook title and \
why it works.

Chapters:
{chapters}

Transcript (segment numbers in brackets):
{format_transcript(episode.segments)}"""
    return _call(client, system, user, Packaging, effort="medium")


def generate_longform(
    client: anthropic.Anthropic,
    figure: Figure,
    index: BM25Index,
    fmt: ShowFormat,
    themes: str = "",
    host_name: str = "Host",
    run_fact_check: bool = True,
    log=print,
) -> Episode:
    log(f"Planning {fmt.minutes}-minute episode in {len(fmt.chapters)} chapters...")
    plan = plan_longform(client, figure, fmt, themes, host_name)
    if len(plan.chapters) != len(fmt.chapters):
        plan.chapters = (plan.chapters + [ChapterPlan(title=c.title, questions=[]) for c in fmt.chapters])[
            : len(fmt.chapters)
        ]

    episode = Episode(figure=figure, topic=themes or fmt.description, title=plan.title, hook=plan.hook,
                      chapters=[], passages={})
    quoted: set[str] = set()
    summaries = []
    for i, chapter_plan in enumerate(plan.chapters):
        log(f"Chapter {i + 1}/{len(plan.chapters)}: {chapter_plan.title}")
        passages = gather_passages(index, chapter_plan.questions)
        written = write_chapter(client, figure, fmt, plan, i, passages, episode.segments, quoted, host_name)
        offset = len(episode.segments)
        episode.chapters.append(Chapter(title=chapter_plan.title, segments=written.segments))
        episode.passages.update(passages)
        quoted.update(c for seg in written.segments for c in seg.citations if '"' in seg.text or "“" in seg.text)
        episode.issues += mechanical_checks(written.segments, passages, offset)
        if run_fact_check:
            result = fact_check(client, figure, written.segments, passages, offset)
            episode.issues += result.issues
            summaries.append(f"{chapter_plan.title}: {result.summary}")

    episode.fact_check_summary = "\n".join(summaries)
    log("Packaging for YouTube...")
    episode.packaging = package(client, figure, episode, host_name)
    return episode
