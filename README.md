# The-Deadman-Show
Podcast channel featuring ai generated historical figures like Sir Isaac Newton, Adam Smith Cleopatra,  based on their available knowledge books, writings, lectures

## Script pipeline

Turns a topic into an interview script in which the guest's answers are built on, and cite,
their own published writings. Adam Smith is the first figure.

```
figures/adam_smith.toml ──► ingest ──► data/adam_smith/passages.jsonl
                                              │
   topic ──► plan questions ──► search passages ──► write script ──► fact-check ──► output/
```

1. **Ingest:** downloads the public-domain texts from Project Gutenberg, strips the
   boilerplate and front matter, and splits them into ~250-word passages. Each passage keeps
   its location, e.g. *Wealth of Nations (1776), Book I > Chapter X*.
2. **Plan:** Claude drafts the host's questions, each with search terms in the figure's own
   period vocabulary ("joint-stock company", not "corporation").
3. **Search:** BM25 keyword search pulls the most relevant passages for each question.
4. **Write:** Claude writes the script in the figure's voice, citing passage ids on each guest
   line. The intro always says the guest is an AI recreation.
5. **Fact-check:** code first checks that every cited passage exists and that every direct
   quotation appears word for word in the cited passages. Claude then reviews the guest lines
   for anachronisms, unsupported claims and out-of-character positions.

### Setup

```bash
pip install -r requirements-dev.txt
export ANTHROPIC_API_KEY=sk-ant-...   # or sign in with `ant auth login`
```

### Usage

```bash
# One-time: download and index Adam Smith's writings (~1,800 passages)
python -m deadman ingest adam_smith

# Optional: check what the search finds
python -m deadman search adam_smith "joint stock company monopoly"

# Generate an episode script
python -m deadman script adam_smith "Would Adam Smith approve of Amazon?" --minutes 12 --host Maya
```

The script goes to `output/adam_smith/<date>-<topic>/`:

- `script.md`: the readable script with numbered source references, a sources list and the
  fact-check findings. Review any flagged issues before recording.
- `episode.json`: the plan, segments, citations and passages, for the voice and video stages
  that come next.

Options for `script`: `--questions N` (default 6), `--minutes N` (default 10),
`--host NAME`, `--no-fact-check`.

### Adding a figure

Create `figures/<slug>.toml` with the persona (dates, biography, voice, core views, knowledge
limits) and a `[[sources]]` entry for each text. See `figures/adam_smith.toml`. Per source:

- `start_line` / `start_occurrence`: the line where the author's text begins. Use this to skip
  tables of contents and editors' introductions.
- `end_line`: where it ends, if back matter follows.
- `heading_levels` / `title_level`: how BOOK, PART and CHAPTER headings nest in that text,
  so that citations show the right location.

Then run `python -m deadman ingest <slug>`.

### Tests

```bash
python -m pytest
```

The tests use a fake Claude client, so they need no API key or network access.
