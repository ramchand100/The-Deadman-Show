"""Load historical-figure personas from figures/<slug>.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

FIGURES_DIR = Path(__file__).resolve().parent.parent / "figures"

DEFAULT_HEADING_LEVELS = {"BOOK": 1, "PART": 1, "SECTION": 2, "CHAPTER": 3, "CHAP.": 3}


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    year: int
    url: str
    start_line: str | None = None
    start_occurrence: int = 1
    end_line: str | None = None
    # Nesting depth of numbered headings ("BOOK I.", "CHAPTER II.") in this text.
    heading_levels: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_HEADING_LEVELS))
    # Depth of unnumbered all-caps titles; 0 means a title starts a new top-level work.
    title_level: int = 0


@dataclass(frozen=True)
class Figure:
    slug: str
    name: str
    speaker_label: str
    born: int
    died: int
    era: str
    summary: str
    voice: str
    guidance: str
    views: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)

    def source(self, source_id: str) -> Source:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise KeyError(f"{self.slug} has no source {source_id!r}")


def load_figure(slug: str, figures_dir: Path = FIGURES_DIR) -> Figure:
    path = figures_dir / f"{slug}.toml"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in figures_dir.glob("*.toml")))
        raise FileNotFoundError(f"No figure {slug!r}. Available: {available}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    sources = [Source(**s) for s in data.pop("sources", [])]
    for key in ("summary", "voice", "guidance"):
        data[key] = data[key].strip()
    return Figure(**data, sources=sources)
