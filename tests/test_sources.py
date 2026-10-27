from deadman.figures import Source, load_figure
from deadman.sources import _tidy_heading, chunk, clean, html_to_text

SOURCE = Source(id="won", title="Wealth of Nations", year=1776, url="", start_line="BOOK I.", start_occurrence=2,
                heading_levels={"BOOK": 1, "CHAPTER": 2, "PART": 3}, title_level=3)

RAW = (
    "Header junk\r\n*** START OF THE PROJECT GUTENBERG EBOOK WEALTH ***\r\n"
    "CONTENTS\r\nBOOK I.\r\nCHAPTER I.\r\n\r\n"
    "BOOK I.\r\nOF THE CAUSES OF IMPROVEMENT.\r\n\r\n"
    "CHAPTER I.\r\nOF THE DIVISION OF LABOUR.\r\n\r\n"
    + ("      The greatest improvement in the productive powers of labour {12} seems to\r\n"
       "      have been the effects of the division of labour.[3]\r\n\r\n") * 12
    + "-----\r\n\r\nA short tail.\r\n\r\n"
    "CHAPTER II.\r\nOF THE PRINCIPLE WHICH GIVES OCCASION TO THE\r\nDIVISION OF LABOUR.\r\n\r\n"
    + "      This division of labour is not originally the effect of any human wisdom. " * 30
    + "\r\n*** END OF THE PROJECT GUTENBERG EBOOK WEALTH ***\r\nLicense text"
)


def test_clean_strips_boilerplate_and_front_matter():
    text = clean(RAW, SOURCE)
    assert "Header junk" not in text and "License text" not in text
    assert "CONTENTS" not in text
    assert text.startswith("BOOK I.")
    assert "{12}" not in text and "[3]" not in text and "-----" not in text
    assert "\r" not in text


def test_chunk_tracks_headings_and_folds_short_tails():
    passages = chunk(clean(RAW, SOURCE), SOURCE)
    assert passages[0].location == "Book I > Chapter I. Of the division of labour"
    assert passages[-1].location == "Book I > Chapter II. Of the principle which gives occasion to the division of labour"
    assert all(len(p.text.split()) >= 40 for p in passages)
    assert any(p.text.endswith("A short tail.") for p in passages)
    assert [p.id for p in passages] == [f"won-{i:04d}" for i in range(len(passages))]


def test_tidy_heading():
    assert _tidy_heading("CHAPTER VIII. OF THE WAGES OF LABOUR.") == "Chapter VIII. Of the wages of labour"
    assert _tidy_heading("PART II.—INEQUALITIES OCCASIONED BY THE POLICY OF EUROPE") == \
        "Part II. Inequalities occasioned by the policy of europe"
    assert _tidy_heading("CHAP. I. Of SYMPATHY.", label_only=True) == "Chap. I"


def test_adam_smith_config_loads():
    smith = load_figure("adam_smith")
    assert smith.died == 1790
    assert {s.id for s in smith.sources} == {"won", "tms", "essays", "rae"}
    assert smith.source("won").heading_levels["PART"] == 3
    assert smith.source("rae").kind == "biography"


def test_html_sources_become_paragraphs():
    html = ("<!DOCTYPE html><html><head><style>p{}</style></head><body>"
            "<p>*** START OF THE PROJECT GUTENBERG EBOOK X ***</p><h2>BOOK I.</h2>"
            "<p>First   paragraph<br>wraps <span class='pagenum'>[Pg 4]</span>here &amp; on.</p>"
            "<p>Second.</p><p>*** END OF THE PROJECT GUTENBERG EBOOK X ***</p></body></html>")
    text = clean(html, Source(id="x", title="X", year=1, url="", start_line="BOOK I."))
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    assert paragraphs == ["BOOK I.", "First paragraph\nwraps here & on.", "Second."]
    assert "p{}" not in html_to_text(html)


def test_isaac_newton_config_loads():
    newton = load_figure("isaac_newton")
    assert (newton.born, newton.died, newton.speaker_label) == (1642, 1727, "NEWTON")
    assert {s.id for s in newton.sources} == {"principia", "opticks", "daniel", "brewster", "chittenden"}
    assert {s.id for s in newton.sources if s.kind == "biography"} == {"brewster", "chittenden"}
    assert newton.source("principia").skip_tables and not load_figure("adam_smith").source("won").skip_tables


def test_extra_heading_words_and_title_levels():
    source = Source(id="o", title="O", year=1, url="", heading_levels={"PART": 2, "PROP.": 3},
                    title_level=2, title_levels={"BOOK OF OPTICKS": 1})
    text = "THE FIRST BOOK OF OPTICKS\n\nPART I.\n\nPROP. I.\n\n" + "Light is made of rays. " * 20
    assert chunk(text, source)[0].location == "The first book of opticks > Part I > Prop. I"
