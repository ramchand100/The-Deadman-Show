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

# Long-form episode (~60 min, chaptered, like today's big interview podcasts)
python -m deadman episode adam_smith --host Ram --themes "AI, India, money and happiness"

# Short single-topic episode
python -m deadman script adam_smith "Would Adam Smith approve of Amazon?" --minutes 12 --host Ram
```

The episode goes to `output/adam_smith/<date>-<title>/`:

- `script.md`: the readable script with chapters, numbered source references, a sources list
  and the fact-check findings. Review any flagged issues before recording. Long-form episodes
  also include the cold open, YouTube title and thumbnail options, and clips for Shorts.
- `youtube-description.txt`: ready to paste, with chapter timestamps and sources.
- `episode.json`: everything above as data, for the voice and video stages that come next.

### Long-form format

`formats/longform.toml` sets the running order: welcome, origins, career, big ideas,
friendship and love, money and happiness, hot takes, regrets and legacy, and a closing
tradition where each guest leaves a question for the next dead guest. Edit the chapters,
minutes and style notes there to change the show without touching code. Each chapter is
written separately with its own source passages. Each chapter also sees how the previous one
ended and which passages were already quoted, so the conversation flows without repeating
itself.

### Sources: writings vs. biography

Each figure has two kinds of source. **Primary** sources are their own writings.
**Biography** sources, such as John Rae's *Life of Adam Smith* (1895), give the persona
memories of its life. The guest tells those events in the first person but never quotes the
biographer's sentences as its own. The figure's own letters, as quoted in the biography, may
be quoted.

Options for `script`: `--questions N` (default 6), `--minutes N` (default 10),
`--host NAME`, `--no-fact-check`.

### Adding a figure

Create `figures/<slug>.toml` with the persona (dates, biography, voice, core views, knowledge
limits) and a `[[sources]]` entry for each text. See `figures/adam_smith.toml`. Per source:

- `start_line` / `start_occurrence`: the line where the author's text begins. Use this to skip
  tables of contents and editors' introductions.
- `end_line`: where it ends, if back matter follows.
- `kind`: `"primary"` (default) or `"biography"`.
- `heading_levels` / `title_level`: how BOOK, PART and CHAPTER headings nest in that text,
  so that citations show the right location.

Then run `python -m deadman ingest <slug>`.

### Tests

```bash
python -m pytest
```

The tests use a fake Claude client, so they need no API key or network access.
