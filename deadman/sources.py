"""Download a figure's public-domain texts and split them into citable passages."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import requests

from .figures import Figure, Source

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

TARGET_WORDS = 220
MAX_WORDS = 420
MIN_WORDS = 40
SUBTITLE_WORDS = 12

_GUTENBERG_START = re.compile(r"^\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG.*$", re.M)
_GUTENBERG_END = re.compile(r"^\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG.*$", re.M)
_PAGE_REF = re.compile(r"\{\d+\}|\[Pg [0-9ivxlc]+\]", re.I)
_FOOTNOTE_REF = re.compile(r"\[\d+\]")
_RULE_LINE = re.compile(r"^[ \t]*[-*=][-*= \t]{2,}$", re.M)
STRUCTURAL_WORDS = ("BOOK", "PART", "SECTION", "CHAPTER", "CHAP.")
_STRUCTURAL = re.compile(r"^(BOOK|PART|SECTION|CHAPTER|CHAP\.)\s+([IVXLC]+)\b", re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


@dataclass
class Passage:
    id: str
    source_id: str
    title: str
    year: int
    location: str
    text: str
    kind: str = "primary"

    def citation(self) -> str:
        where = f", {self.location}" if self.location else ""
        return f"{self.title} ({self.year}){where}"


def figure_dir(figure: Figure, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / figure.slug


def download(source: Source, raw_dir: Path, force: bool = False) -> str:
    path = raw_dir / f"{source.id}.txt"
    if path.exists() and not force:
        return path.read_text(encoding="utf-8")
    resp = requests.get(source.url, timeout=60)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(resp.text, encoding="utf-8")
    return resp.text


class _TextExtractor(HTMLParser):
    """HTML to plain text: each block element becomes its own paragraph, like a Gutenberg .txt."""

    BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote", "table", "hr"}
    SKIP = {"script", "style", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag in self.BLOCKS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BLOCKS:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(re.sub(r"[ \t\r\n]+", " ", data))


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    text = unescape("".join(extractor.parts))
    lines = [line.strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def _find_line(lines: list[str], target: str, occurrence: int, start: int = 0) -> int:
    seen = 0
    for i in range(start, len(lines)):
        if lines[i].strip().replace("_", "") == target.replace("_", ""):
            seen += 1
            if seen == occurrence:
                return i
    raise ValueError(f"Line {target!r} (occurrence {occurrence}) not found")


def clean(raw: str, source: Source) -> str:
    """Strip Gutenberg boilerplate and front/back matter, keeping the author's text."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    if text.lstrip()[:15].lower().startswith(("<!doctype", "<html", "<?xml")):
        text = html_to_text(text)
    if m := _GUTENBERG_START.search(text):
        text = text[m.end():]
    if m := _GUTENBERG_END.search(text):
        text = text[: m.start()]

    lines = text.split("\n")
    begin = _find_line(lines, source.start_line, source.start_occurrence) if source.start_line else 0
    end = _find_line(lines, source.end_line, 1, begin) if source.end_line else len(lines)
    text = "\n".join(lines[begin:end])

    text = _PAGE_REF.sub("", text)
    text = _FOOTNOTE_REF.sub("", text)
    text = _RULE_LINE.sub("", text)
    return text.replace("_", "")


def _paragraphs(text: str) -> list[str]:
    paras = []
    for block in re.split(r"\n\s*\n", text):
        joined = " ".join(line.strip() for line in block.split("\n") if line.strip())
        if joined:
            paras.append(joined)
    return paras


@lru_cache
def _structural_pattern(words: tuple[str, ...]) -> re.Pattern:
    """Numbered headings: one of the words, then a roman numeral ("BOOK II", "PROP. IV")."""
    alternatives = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"^({alternatives})\s+([IVXLC]+)\b", re.I)


def structural_pattern(source: Source) -> re.Pattern:
    """The default heading words plus any extra ones a source declares in heading_levels."""
    return _structural_pattern(tuple(sorted(set(STRUCTURAL_WORDS) | set(source.heading_levels))))


def _is_structural(para: str, pattern: re.Pattern = _STRUCTURAL) -> bool:
    return len(para) < 300 and bool(pattern.match(para))


def _is_mostly_text(para: str) -> bool:
    """False for tables of figures and symbols, which make useless passages."""
    letters = sum(c.isalpha() for c in para)
    return letters >= 0.5 * len(para.replace(" ", ""))


def _is_caps_title(para: str) -> bool:
    return len(para) < 120 and any(c.isalpha() for c in para) and para == para.upper()


def _heading_level(heading: str, source: Source) -> int:
    m = structural_pattern(source).match(heading)
    if not m:
        for pattern, level in source.title_levels.items():
            if re.search(pattern, heading, re.I):
                return level
        return source.title_level
    return source.heading_levels.get(m.group(1).upper(), max(source.heading_levels.values()))


def _tidy_heading(heading: str, label_only: bool = False, pattern: re.Pattern = _STRUCTURAL) -> str:
    """'CHAPTER VIII. OF THE WAGES OF LABOUR.' -> 'Chapter VIII. Of the wages of labour'."""
    heading = heading.strip().rstrip(".")
    m = pattern.match(heading)
    if m:
        label = f"{m.group(1).capitalize()} {m.group(2).upper()}"
        if label_only:
            return label
        rest = heading[m.end():].lstrip(" .—-").lower()
        return f"{label}. {rest[:1].upper()}{rest[1:]}" if rest else label
    heading = heading.lower()
    return heading[:1].upper() + heading[1:]


def _split_long(para: str) -> list[str]:
    if len(para.split()) <= MAX_WORDS:
        return [para]
    pieces, current = [], []
    for sentence in _SENTENCE_END.split(para):
        current.append(sentence)
        if sum(len(s.split()) for s in current) >= TARGET_WORDS:
            pieces.append(" ".join(current))
            current = []
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk(text: str, source: Source) -> list[Passage]:
    """Group paragraphs into ~TARGET_WORDS passages that never cross a heading."""
    pattern = structural_pattern(source)
    passages: list[Passage] = []
    levels: dict[int, str] = {}
    buffer: list[str] = []
    pending: list[str] = []

    def location() -> str:
        keys = sorted(levels)
        return " > ".join(_tidy_heading(levels[k], label_only=k != keys[-1], pattern=pattern) for k in keys)

    def flush() -> None:
        if not buffer:
            return
        text, loc = " ".join(buffer), location()
        buffer.clear()
        # Fold a short tail (end of a chapter, a stray line) into the passage before it.
        if len(text.split()) < MIN_WORDS and passages and passages[-1].location == loc:
            passages[-1].text += " " + text
            return
        passages.append(Passage(
            id=f"{source.id}-{len(passages):04d}",
            source_id=source.id,
            title=source.title,
            year=source.year,
            location=loc,
            text=text,
            kind=source.kind,
        ))

    def apply_heading() -> None:
        heading = " ".join(pending)
        pending.clear()
        level = _heading_level(heading, source)
        for k in [k for k in levels if k >= level]:
            del levels[k]
        levels[level] = heading

    in_footnotes = False
    for para in _paragraphs(text):
        if _is_structural(para, pattern):
            flush()
            if pending:
                apply_heading()
            pending.append(para)
            in_footnotes = False
        elif in_footnotes:
            continue
        elif para.upper().startswith("FOOTNOTES"):
            # Editors' notes run until the next numbered heading.
            flush()
            in_footnotes = True
        elif _is_caps_title(para):
            # Multi-line titles and subtitles join the heading in progress.
            flush()
            pending.append(para)
        elif source.skip_tables and not _is_mostly_text(para):
            continue
        elif pending and len(para.split()) <= SUBTITLE_WORDS:
            pending.append(para)
        else:
            if pending:
                apply_heading()
            for piece in _split_long(para):
                buffer.append(piece)
                if sum(len(p.split()) for p in buffer) >= TARGET_WORDS:
                    flush()
    flush()
    return passages


def ingest(figure: Figure, data_dir: Path = DATA_DIR, force: bool = False) -> list[Passage]:
    """Download, clean and chunk every source for a figure; write passages.jsonl."""
    out_dir = figure_dir(figure, data_dir)
    passages: list[Passage] = []
    for source in figure.sources:
        raw = download(source, out_dir / "raw", force=force)
        passages.extend(chunk(clean(raw, source), source))
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "passages.jsonl").open("w", encoding="utf-8") as f:
        for p in passages:
            f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
    return passages


def load_passages(figure: Figure, data_dir: Path = DATA_DIR) -> list[Passage]:
    path = figure_dir(figure, data_dir) / "passages.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"No passages for {figure.slug}. Run: python -m deadman ingest {figure.slug}")
    with path.open(encoding="utf-8") as f:
        return [Passage(**json.loads(line)) for line in f if line.strip()]
