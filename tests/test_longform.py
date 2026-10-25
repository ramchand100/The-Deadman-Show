from deadman.figures import load_figure
from deadman.longform import (
    ChapterPlan,
    ChapterScript,
    Clip,
    LongformPlan,
    Packaging,
    generate_longform,
    load_format,
)
from deadman.render import chapter_timestamps, to_markdown, youtube_description
from deadman.retrieval import BM25Index
from deadman.script import FactCheck, PlannedQuestion, Segment
from tests.test_script import PASSAGES, FakeClient


def test_longform_format_loads():
    fmt = load_format("longform")
    assert fmt.chapters[0].id == "welcome" and fmt.chapters[-1].id == "closing"
    assert 50 <= fmt.minutes <= 90


def test_generate_longform_writes_each_chapter_and_packages():
    figure = load_figure("adam_smith")
    fmt = load_format("longform")
    n = len(fmt.chapters)
    q = PlannedQuestion(question="Tell me about pins", search_terms=["pin manufactory"])
    plan = LongformPlan(title="Adam Smith: Pins and Plots", hook="h",
                        chapters=[ChapterPlan(title=f"Ch {i}", questions=[q]) for i in range(n)])
    chapters = [
        ChapterScript(segments=[
            Segment(speaker="HOST", text="word " * 150, citations=[]),
            Segment(speaker="GUEST", text='"The division of labour in a pin manufactory" indeed.', citations=["won-0002"]),
        ])
        for _ in range(n)
    ]
    checks = [FactCheck(summary="ok", issues=[]) for _ in range(n)]
    packaging = Packaging(title_options=["T1"], thumbnail_text=["PINS!"], description="About pins.",
                          cold_open_start=1, cold_open_end=1,
                          clips=[Clip(start_segment=0, end_segment=1, title="Pins", why="fun")])
    # Calls alternate: plan, then (write, fact-check) per chapter, then packaging.
    outputs = [plan] + [x for pair in zip(chapters, checks) for x in pair] + [packaging]
    client = FakeClient(outputs)

    ep = generate_longform(client, figure, BM25Index(list(PASSAGES.values())), fmt, host_name="Ram",
                           log=lambda *_: None)

    assert len(client.requests) == 1 + 2 * n + 1
    assert [ch.title for ch in ep.chapters] == [f"Ch {i}" for i in range(n)]
    assert ep.issues == []
    # The second chapter is told how the first ended and which passages were already quoted.
    second_write = client.requests[3]["messages"][0]["content"]
    assert "How the previous chapter ended" in second_write and "won-0002" in second_write.split("already quoted")[1]

    stamps = chapter_timestamps(ep)
    assert stamps[0] == ("0:00", "Ch 0") and stamps[1][0] == "1:07"  # 9-word cold open + 159-word chapter
    md = to_markdown(ep, host_name="Ram")
    assert "## Cold open" in md and "### Ch 3" in md and "**Pins** (segments 0-1)" in md
    desc = youtube_description(ep)
    assert desc.startswith("About pins.") and "1:07 Ch 1" in desc and "AI recreation" in desc
