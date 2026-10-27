import pytest

from deadman.episodes import (
    Brief,
    EpisodeFileError,
    check_episode,
    load_packaging,
    new_episode,
    next_number,
    parse_transcript,
    pending_question,
    write_packaging,
    write_transcript,
)
from deadman.figures import load_figure
from deadman.longform import Clip, Packaging
from deadman.script import Episode
from tests.test_script import PASSAGES

TRANSCRIPT = """# Pins and Plots
> A hook.

## Welcome

RAM: Welcome. My guest is an AI recreation of Adam Smith,
built from his writings.

SMITH: Thank you.

## Pins

RAM: Tell me about pins.

SMITH: "The division of labour in a pin manufactory" is my favourite example. [won-0002]

RAM: Thanks. You've been listening to an AI recreation.
"""


def parse():
    return parse_transcript(TRANSCRIPT, "Ram", "SMITH")


def make_episode():
    title, hook, chapters = parse()
    return Episode(figure=load_figure("adam_smith"), topic="", title=title, hook=hook,
                   chapters=chapters, passages=PASSAGES)


def test_parse_transcript_reads_chapters_speakers_and_citations():
    title, hook, chapters = parse()
    assert (title, hook) == ("Pins and Plots", "A hook.")
    assert [c.title for c in chapters] == ["Welcome", "Pins"]
    first = chapters[0].segments[0]
    assert first.speaker == "HOST" and first.text.endswith("built from his writings.")
    assert chapters[1].segments[1].citations == ["won-0002"]
    assert chapters[1].segments[1].text.endswith("favourite example.")


def test_transcript_round_trips():
    ep = make_episode()
    assert parse_transcript(write_transcript(ep, "Ram"), "Ram", "SMITH")[2] == ep.chapters


def test_unknown_speaker_is_an_error():
    with pytest.raises(EpisodeFileError, match="unknown speaker 'LEX'"):
        parse_transcript("# T\n\nLEX: hello", "Ram", "SMITH")


def test_packaging_anchors_survive_edits(tmp_path):
    ep = make_episode()
    p = Packaging(title_options=["T"], thumbnail_text=["X"], description="D", cold_open_start=3,
                  cold_open_end=4, clips=[Clip(start_segment=2, end_segment=3, title="Pins", why="w")])
    path = tmp_path / "packaging.toml"
    path.write_text(write_packaging(p, ep.segments))
    # Insert a line before the clip; anchors are text, so the clip still finds its lines.
    ep.chapters[1].segments.insert(0, ep.chapters[0].segments[1].model_copy(update={"text": "An inserted line."}))
    loaded = load_packaging(path, ep.segments)
    assert (loaded.clips[0].start_segment, loaded.clips[0].end_segment) == (3, 4)
    assert ep.segments[loaded.cold_open_start].text.startswith("\"The division")


def test_check_requires_disclosure_and_flags_misquotes():
    ep = make_episode()
    brief = Brief(number=1, figure="adam_smith", host="Ram", format="")
    assert check_episode(ep, brief).errors == []
    ep.chapters[0].segments[0].text = "Welcome."
    ep.chapters[1].segments[1].text = '"Pins are the root of all wealth, truly" I said.'
    kinds = sorted(i.kind for i in check_episode(ep, brief).errors)
    assert kinds == ["disclosure", "misquote"]


def test_closing_disclosure_only_required_once_every_chapter_is_written():
    ep = make_episode()
    brief = Brief(number=1, figure="adam_smith", host="Ram", format="")
    ep.chapters[1].segments[-1].text = "Thanks."
    assert [i.excerpt for i in check_episode(ep, brief).errors] == ["closing"]
    ep.chapters.append(type(ep.chapters[0])(title="Later", segments=[]))
    report = check_episode(ep, brief)
    assert report.errors == [] and any("closing line" in w for w in report.warnings)


def test_check_warns_when_far_short_of_format_length():
    report = check_episode(make_episode(), Brief(number=1, figure="adam_smith", host="Ram", format="longform"))
    assert any("chapters" in w for w in report.warnings)
    assert any("under the" in w for w in report.warnings)


def test_new_episode_numbers_folders_and_writes_templates(tmp_path):
    smith = load_figure("adam_smith")
    first = new_episode(smith, "Ram", root=tmp_path)
    second = new_episode(smith, "Ram", themes="AI", slug="Smith on AI", root=tmp_path)
    assert first.name == "001-adam-smith" and second.name == "002-smith-on-ai"
    assert next_number(tmp_path) == 3
    assert (second / "brief.toml").read_text().count('themes = "AI"') == 1
    assert "## Where it all began" in (second / "transcript.md").read_text()
    assert (second / "research" / "02-origins.md").read_text().startswith("# Where it all began")


def test_pending_question_reads_newest_unanswered_row(tmp_path):
    path = tmp_path / "q.md"
    path.write_text("| Episode | Asked by | Question | Answered by |\n|---|---|---|---|\n"
                    "| 002 | Adam Smith | Old one? | Isaac Newton (003) |\n"
                    "| 003 | Isaac Newton | New one? | *(next guest)* |\n")
    assert pending_question(path) == ("Isaac Newton", "New one?")
    assert pending_question(tmp_path / "missing.md") is None
