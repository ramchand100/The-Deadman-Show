from types import SimpleNamespace

import pytest

from deadman.figures import load_figure
from deadman.render import to_markdown
from deadman.retrieval import BM25Index
from deadman.script import (
    EpisodePlan,
    FactCheck,
    GenerationError,
    Issue,
    PlannedQuestion,
    Script,
    Segment,
    generate_episode,
    mechanical_checks,
)
from deadman.sources import Passage

PASSAGES = {
    "won-0001": Passage("won-0001", "won", "Wealth of Nations", 1776, "Book I > Chapter X",
                        "People of the same trade seldom meet together, even for merriment and diversion, "
                        "but the conversation ends in a conspiracy against the public."),
    "won-0002": Passage("won-0002", "won", "Wealth of Nations", 1776, "Book I > Chapter I",
                        "The division of labour in a pin manufactory greatly increases the quantity of work."),
}


class FakeClient:
    """Returns canned structured outputs in call order and records each request."""

    def __init__(self, outputs, stop_reason="end_turn"):
        self.outputs = list(outputs)
        self.requests = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            stop_details=SimpleNamespace(explanation="declined") if self.stop_reason == "refusal" else None,
            parsed_output=self.outputs.pop(0) if self.outputs else None,
        )


def guest(text, *citations):
    return Segment(speaker="GUEST", text=text, citations=list(citations))


def test_mechanical_checks_accepts_verbatim_quotes():
    script = Script(title="t", segments=[
        guest('As I wrote, "people of the same trade seldom meet together" without mischief.', "won-0001"),
    ])
    assert mechanical_checks(script.segments, PASSAGES) == []


def test_mechanical_checks_flags_invented_quotes_and_unknown_ids():
    script = Script(title="t", segments=[
        Segment(speaker="HOST", text='He said "greed is good, always and everywhere".', citations=[]),
        guest('I always said "greed is good, always and everywhere".', "won-0001"),
        guest("Pins, sir, pins.", "won-9999"),
    ])
    issues = mechanical_checks(script.segments, PASSAGES, offset=10)
    assert [(i.segment, i.kind) for i in issues] == [(11, "misquote"), (12, "unsupported")]


def test_mechanical_checks_pairs_quote_marks_in_order():
    script = Script(title="t", segments=[
        guest('One said "Hegh sirs!" and the other said "the conversation ends in a conspiracy against the public".',
              "won-0001"),
    ])
    assert mechanical_checks(script.segments, PASSAGES) == []


def test_generate_episode_runs_plan_write_and_fact_check():
    figure = load_figure("adam_smith")
    plan = EpisodePlan(title="Smith on Pins", hook="A hook.", questions=[
        PlannedQuestion(question="Why do factories split up work?", search_terms=["division of labour", "pin"]),
    ])
    script = Script(title="Smith on Pins", segments=[
        Segment(speaker="HOST", text="Welcome. Our guest is an AI recreation of Adam Smith.", citations=[]),
        guest("Consider a pin manufactory.", "won-0002"),
    ])
    check = FactCheck(summary="Clean.", issues=[
        Issue(segment=1, kind="unsupported", excerpt="pin", explanation="x", suggested_fix="y"),
    ])
    client = FakeClient([plan, script, check])

    ep = generate_episode(client, figure, BM25Index(list(PASSAGES.values())), "pins", log=lambda *_: None)

    assert ep.segments == script.segments and ep.title == "Smith on Pins"
    assert "won-0002" in ep.passages
    assert len(client.requests) == 3
    write_prompt = client.requests[1]["messages"][0]["content"]
    assert 'id="won-0002"' in write_prompt and "Why do factories split up work?" in write_prompt
    assert all(r["model"] == "claude-opus-5-5" and r["fallbacks"] == "default" for r in client.requests)
    assert [i.kind for i in ep.issues] == ["unsupported"]

    md = to_markdown(ep, host_name="Maya")
    assert "**MAYA:** Welcome." in md
    assert "**SMITH:** Consider a pin manufactory. [1]" in md
    assert "1. Wealth of Nations (1776), Book I > Chapter I" in md


def test_refusal_raises_generation_error():
    figure = load_figure("adam_smith")
    client = FakeClient([], stop_reason="refusal")
    with pytest.raises(GenerationError, match="declined"):
        generate_episode(client, figure, BM25Index(list(PASSAGES.values())), "pins", log=lambda *_: None)
