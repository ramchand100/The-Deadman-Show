---
name: add-figure
description: Add a new historical figure to The Deadman Show. Finds public-domain texts by and about them, writes figures/<slug>.toml (persona and sources), ingests and verifies the passages. Use when the user wants a guest who has no figures/<slug>.toml yet, e.g. "add Isaac Newton" or "/add-figure cleopatra".
---

# Add a figure

Work from the repository root. Read `show/bible.md` and use `figures/adam_smith.toml` as
the template.

## 1. Find sources

Look for public-domain texts on Project Gutenberg (`https://www.gutenberg.org/ebooks/search/?query=...`;
plain text at `https://www.gutenberg.org/cache/epub/<id>/pg<id>.txt`):

- **Primary:** the figure's own writings, speeches, letters and lectures, in English
  (a public-domain translation if needed). Prefer the most complete edition, and note the
  edition year: later editions can add or remove famous passages.
- **Biography:** at least one public-domain biography, ideally by someone who knew the
  figure or worked from their letters. Older biographies quote letters, which gives the
  guest real words to use.

Download each candidate into the scratchpad and check it before choosing it: is it the
right work, is the text complete, and is it English?

If the figure left almost no writings (Cleopatra, Socrates), say so to the user. Their
sources are all `kind = "biography"` (ancient historians such as Plutarch), and the persona's
`guidance` must say the guest is reconstructed from what others wrote and must never quote
those writers as their own words.

## 2. Map each text's structure

For each text, find in the downloaded file:

- `start_line`: the exact line (stripped) where the author's text begins, and
  `start_occurrence` if it also appears in the table of contents (usually 2).
- `end_line`: where back matter (index, appendix by an editor, transcriber's notes) begins.
- The headings it uses (BOOK, PART, CHAPTER, SECTION, CHAP.) and how they nest, for
  `heading_levels`, plus `title_level` for unnumbered all-caps titles.

## 3. Write figures/<slug>.toml

Fill every field: `name`, `speaker_label` (surname in capitals, e.g. NEWTON), `born`, `died`,
`era`, `summary`, `voice` (how they spoke and wrote, with their characteristic examples),
`views` (6-8 core positions, each traceable to their writings), `guidance` (death year,
knowledge limits, period vocabulary to keep and modern vocabulary to avoid, sensitive areas),
and the `[[sources]]` entries.

## 4. Ingest and verify

```bash
python -m deadman ingest <slug>
python -m deadman search <slug> "<a famous idea in their words>"
python -m deadman search <slug> "<a famous life event>" --kind biography
```

Check: passage counts per source look right; locations read like "Book I > Chapter III. ..."
rather than tables of contents or footnotes; the first and last passages of each source are
the author's text. Fix the TOML and re-ingest until they are.

Add a test line for the new figure to `tests/test_sources.py`
(`test_<slug>_config_loads`), run `python -m pytest`, then commit `figures/<slug>.toml` and
the test. `data/` is not committed.

## 5. Report

Tell the user: the sources chosen (with years and editions), passage counts, notable gaps
(for example missing editions, no letters, no own writings), and that the figure is ready for
`/new-episode <slug>`.
