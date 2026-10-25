from deadman.figures import Source, load_figure
from deadman.sources import _tidy_heading, chunk, clean

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
    assert {s.id for s in smith.sources} == {"won", "tms", "essays"}
    assert smith.source("won").heading_levels["PART"] == 3
