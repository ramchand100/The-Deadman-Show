---
name: new-episode
description: Produce a complete Deadman Show episode (research, script, fact-check, packaging, render) for a historical figure, using the researcher, scriptwriter and fact-checker agents. Use when the user asks for a new episode, e.g. "/new-episode isaac_newton" or "make an episode with Lincoln about leadership".
---

# New episode

Arguments: the figure's slug (see `figures/`), and optionally themes, host name (default
Ram) and format (default `longform`). If the user names a figure with no `figures/<slug>.toml`,
run the `add-figure` skill first.

Work from the repository root. Read `show/bible.md` before starting; every stage follows it.
Tell the user in a line or two at each stage what is happening. Do not skip stages.

## 1. Set up

```bash
python -m deadman ingest <figure>          # only if data/<figure>/passages.jsonl is missing
python -m deadman new <figure> --host Ram --themes "<themes>" --slug "<short-name>"
```

Note the new folder (e.g. `episodes/003-isaac-newton`) and its research files.

## 2. Research (parallel)

Split the research files into 3 groups of consecutive chapters and launch one **researcher**
agent per group in the same turn, in the background. Give each: the episode folder, the
exact research files it owns, the themes, and (for the group with the last chapter) a note
to find material for the pending question in `show/next-guest-questions.md`.

When all have finished, skim the research files. If a chapter is thin (fewer than 3 usable
passages or no story), send that researcher back with specific follow-ups before writing.

## 3. Write (in order)

Launch the **scriptwriter** agent in three sequential calls, each covering about a third of
the chapters, so each call can read what came before. Each call must end with
`deadman check` passing (0 errors). Then write the title and hook at the top of
`transcript.md` if the scriptwriter has not.

## 4. Fact-check (independent)

Launch the **fact-checker** agent on the episode folder. It writes `review.md` and does not
edit the transcript. Do not pass it the scriptwriter's notes or reasoning: its independence
is the point.

## 5. Fix

If review.md lists issues, launch the **scriptwriter** to apply them, then run the
**fact-checker** again on the changed lines only. Repeat until the result is
"Ready to record" or only host claims to verify remain. Do not hide issues: unresolved ones
stay in review.md.

## 6. Package

Write `packaging.toml` in the episode folder following the bible's packaging rules:

```toml
title_options = ["...", "..."]          # 5, under 70 characters
thumbnail_text = ["...", "..."]         # 3 options, 2-5 words
description = "..."                     # 2 paragraphs, ends with the AI-recreation sentence
cold_open_from = "<first words of a transcript line>"
cold_open_to = "<first words of a transcript line>"

[[clips]]                               # 8-12 clips
title = "..."
why = "..."
from = "<first words of the first line>"
to = "<first words of the last line>"
```

`from`/`to` are snippets of transcript lines, unique enough to match exactly one line.

## 7. Render and record the tradition

```bash
python -m deadman render <number>
```

Fix anything it reports. Then update `show/next-guest-questions.md`: mark the previous
question as answered by this guest (with the episode number) and add this guest's question
as a new row with `*(next guest)*`.

## 8. Commit and report

Commit the episode folder and the questions file with a clear message, then push to the
working branch. Report to the user: title, length, chapters, the strongest moments, the
review result, and the host claims they must verify before publishing. Send them
`script.md` and `youtube-description.txt`.
