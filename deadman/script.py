"""Plan, write and fact-check an episode script grounded in a figure's own writings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, TypeVar

import anthropic
from pydantic import BaseModel

from .figures import Figure
from .retrieval import BM25Index
from .sources import Passage

MODEL = "claude-opus-5-5"
# Re-run a declined request on Anthropic's recommended fallback model instead of failing.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WORDS_PER_MINUTE = 150
PASSAGES_PER_QUESTION = 4

T = TypeVar("T", bound=BaseModel)


class PlannedQuestion(BaseModel):
    question: str
    search_terms: list[str]


class EpisodePlan(BaseModel):
    title: str
    hook: str
    questions: list[PlannedQuestion]


class Segment(BaseModel):
    speaker: Literal["HOST", "GUEST"]
    text: str
    citations: list[str]


class Script(BaseModel):
    title: str
    segments: list[Segment]


class Issue(BaseModel):
    segment: int
    kind: Literal["anachronism", "unsupported", "misquote", "out_of_character", "disclosure"]
    excerpt: str
    explanation: str
    suggested_fix: str


class FactCheck(BaseModel):
    summary: str
    issues: list[Issue]


@dataclass
class Chapter:
    title: str
    segments: list[Segment]


@dataclass
class Episode:
    figure: Figure
    topic: str
    title: str
    hook: str
    chapters: list[Chapter]
    passages: dict[str, Passage]
    issues: list[Issue] = field(default_factory=list)
    fact_check_summary: str = ""
    # YouTube packaging (title options, clips, cold open); set by the long-form pipeline.
    packaging: BaseModel | None = None

    @property
    def segments(self) -> list[Segment]:
        return [seg for ch in self.chapters for seg in ch.segments]


class GenerationError(RuntimeError):
    pass


def _call(client: anthropic.Anthropic, system: str, user: str, output: type[T], effort: str = "high") -> T:
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_format=output,
    )
    if response.stop_reason == "refusal":
        details = response.stop_details
        raise GenerationError(f"Model declined the request: {details.explanation if details else 'no details'}")
    if response.stop_reason == "max_tokens":
        raise GenerationError("Response hit max_tokens before finishing; try fewer questions or a shorter episode")
    if response.parsed_output is None:
        raise GenerationError("Model returned no structured output")
    return response.parsed_output


def persona_prompt(figure: Figure) -> str:
    views = "\n".join(f"- {v}" for v in figure.views)
    return f"""You write scripts for "The Deadman Show", a YouTube podcast where a modern host \
interviews AI recreations of historical figures. Every episode states that the guest is an AI \
recreation built from the figure's own published writings.

This episode's guest is {figure.name} ({figure.born}-{figure.died}), {figure.era}.

<biography>
{figure.summary}
</biography>

<voice>
{figure.voice}
</voice>

<core_views>
{views}
</core_views>

<knowledge_limits>
{figure.guidance}
</knowledge_limits>

Source passages come in two kinds. kind="primary" passages are the guest's own writings. \
kind="biography" passages were written about the guest by a later biographer: treat the events, \
people and places in them as the guest's own memories and tell them in the first person, but \
never present the biographer's sentences as the guest's words. The guest's own letters quoted \
inside a biography passage are the guest's words and may be quoted.

Rules for the guest's lines:
- Ground substantive claims in the source passages you are given, and cite the passage ids \
each line relies on. Paraphrase in the guest's own voice; quote directly only when the words \
appear verbatim in a cited passage, and put direct quotations in double quotes.
- Purely conversational lines (greetings, reactions, jokes) may have no citations.
- If the passages do not support an answer, have the guest say that their writings do not \
settle the matter, then reason cautiously from the principles they do contain.
- Never put words in the guest's mouth that contradict the guest's writings to make the show more \
dramatic. Disagreement with modern views is fine when the writings support it.

Rules for the host's lines: curious, warm, briefly explains modern context the guest cannot \
know, and asks follow-ups. Host lines have no citations."""


def plan_episode(client: anthropic.Anthropic, figure: Figure, topic: str, n_questions: int) -> EpisodePlan:
    user = f"""Plan an interview episode on this topic: {topic}

Write {n_questions} questions the host will ask, in a sensible order that builds through the \
episode. For each question, give 3-6 search terms that would find the relevant parts of \
{figure.name}'s writings. Write the search terms in {figure.name}'s own vocabulary and \
spelling (period words for the concepts involved), not modern jargon. Also give the episode \
a title and a one-sentence hook for the YouTube description."""
    return _call(client, persona_prompt(figure), user, EpisodePlan, effort="medium")


def gather_passages(
    index: BM25Index, questions: list[PlannedQuestion], k: int = PASSAGES_PER_QUESTION
) -> dict[str, Passage]:
    found: dict[str, Passage] = {}
    for q in questions:
        query = " ".join([q.question, *q.search_terms])
        for passage, _ in index.search(query, k=k):
            found.setdefault(passage.id, passage)
    return found


def _format_passages(passages: dict[str, Passage]) -> str:
    return "\n\n".join(
        f'<passage id="{p.id}" kind="{p.kind}" source="{p.citation()}">\n{p.text}\n</passage>'
        for p in passages.values()
    )


def write_script(
    client: anthropic.Anthropic,
    figure: Figure,
    topic: str,
    plan: EpisodePlan,
    passages: dict[str, Passage],
    minutes: int,
    host_name: str,
) -> Script:
    questions = "\n".join(f"{i}. {q.question}" for i, q in enumerate(plan.questions, 1))
    user = f"""Write the full script for this episode.

Title: {plan.title}
Topic: {topic}
Host name: {host_name}
Target length: about {minutes * WORDS_PER_MINUTE} words (~{minutes} minutes spoken).

Open with a short host introduction that includes the AI-recreation disclosure, then cover \
these questions in order, with natural follow-ups:
{questions}

Close with the host thanking the guest and a one-line sign-off.

Source passages from {figure.name}'s writings (cite them by id):

{_format_passages(passages)}"""
    return _call(client, persona_prompt(figure), user, Script, effort="high")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def _quotations(text: str, min_len: int = 12) -> list[str]:
    """Quoted spans long enough to check. Quote marks are paired in order, so a short quote
    ("Hegh sirs!") never pairs its closing mark with the next quote's opening mark."""
    spans = re.findall(r'"([^"]*)"|“([^”]*)”', text)
    return [s for pair in spans for s in pair if len(s) >= min_len]


def mechanical_checks(segments: list[Segment], passages: dict[str, Passage], offset: int = 0) -> list[Issue]:
    """Checks that need no model: unknown citations and quotations not found in the sources.

    `offset` is the episode-wide index of segments[0], so issues point at the right segment.
    """
    issues = []
    for i, seg in enumerate(segments, offset):
        if seg.speaker != "GUEST":
            continue
        unknown = [c for c in seg.citations if c not in passages]
        if unknown:
            issues.append(Issue(
                segment=i, kind="unsupported", excerpt=seg.text[:80],
                explanation=f"Cites passage ids that were not provided: {', '.join(unknown)}",
                suggested_fix="Cite a provided passage or remove the claim.",
            ))
        cited_text = _normalize(" ".join(passages[c].text for c in seg.citations if c in passages))
        for quote in _quotations(seg.text):
            if _normalize(quote) not in cited_text:
                issues.append(Issue(
                    segment=i, kind="misquote", excerpt=quote[:80],
                    explanation="Direct quotation does not appear verbatim in the cited passages.",
                    suggested_fix="Paraphrase without quotation marks, or quote the source exactly.",
                ))
    return issues


def format_transcript(segments: list[Segment], offset: int = 0) -> str:
    return "\n".join(
        f"[{i}] {seg.speaker} (cites: {', '.join(seg.citations) or 'none'}): {seg.text}"
        for i, seg in enumerate(segments, offset)
    )


def fact_check(
    client: anthropic.Anthropic, figure: Figure, segments: list[Segment], passages: dict[str, Passage], offset: int = 0
) -> FactCheck:
    lines = format_transcript(segments, offset)
    system = f"""You are the fact-checker for a history podcast. You review scripts in which an \
AI recreation of {figure.name} ({figure.born}-{figure.died}) is interviewed. You are strict \
and specific, and you only flag real problems."""
    user = f"""Review the GUEST lines of this script against the source passages.

Flag:
- anachronism: the guest claims knowledge of events, ideas, vocabulary or technology from \
after {figure.died} as their own (reacting to something the host just explained is fine).
- unsupported: a substantive claim about the guest's views that the cited passages do not \
support, or that misrepresents them.
- misquote: words presented as a direct quotation that are not in the passages, or a \
biographer's sentences presented as the guest's own words.
- out_of_character: the guest takes a position their own writings contradict.

Use the segment number in brackets. Return an empty issues list if the script is clean.

<script>
{lines}
</script>

<passages>
{_format_passages(passages)}
</passages>"""
    return _call(client, system, user, FactCheck, effort="high")


def generate_episode(
    client: anthropic.Anthropic,
    figure: Figure,
    index: BM25Index,
    topic: str,
    minutes: int = 10,
    n_questions: int = 6,
    host_name: str = "Host",
    run_fact_check: bool = True,
    log=print,
) -> Episode:
    log(f"Planning episode on {topic!r}...")
    plan = plan_episode(client, figure, topic, n_questions)
    passages = gather_passages(index, plan.questions)
    log(f"Retrieved {len(passages)} passages. Writing script...")
    script = write_script(client, figure, topic, plan, passages, minutes, host_name)
    episode = Episode(
        figure=figure, topic=topic, title=script.title, hook=plan.hook,
        chapters=[Chapter(title=script.title, segments=script.segments)], passages=passages,
    )
    episode.issues = mechanical_checks(script.segments, passages)
    if run_fact_check:
        log("Fact-checking...")
        result = fact_check(client, figure, script.segments, passages)
        episode.issues.extend(result.issues)
        episode.fact_check_summary = result.summary
    return episode
