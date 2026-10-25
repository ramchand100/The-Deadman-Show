"""Write an episode to disk as a readable script (Markdown) and machine-readable JSON."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .script import Episode

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def slugify(text: str, max_len: int = 50) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len].rstrip("-")


def to_markdown(ep: Episode, host_name: str = "Host") -> str:
    speakers = {"HOST": host_name.upper(), "GUEST": ep.figure.speaker_label}
    cited = [c for seg in ep.script.segments for c in seg.citations if c in ep.passages]
    numbers = {pid: n for n, pid in enumerate(dict.fromkeys(cited), 1)}

    out = [f"# {ep.script.title}", "", f"*{ep.plan.hook}*", "",
           f"Guest: {ep.figure.name} (AI recreation) · Topic: {ep.topic}", ""]
    if ep.issues:
        out += [f"> **Review needed:** {len(ep.issues)} fact-check issue(s). See the end of this file.", ""]
    out += ["## Script", ""]
    for seg in ep.script.segments:
        refs = "".join(f"[{numbers[c]}]" for c in seg.citations if c in numbers)
        out += [f"**{speakers[seg.speaker]}:** {seg.text}{' ' + refs if refs else ''}", ""]

    out += ["## Sources", ""]
    for pid, n in numbers.items():
        out.append(f"{n}. {ep.passages[pid].citation()} — passage `{pid}`")
    out.append("")

    out += ["## Fact check", ""]
    if ep.fact_check_summary:
        out += [ep.fact_check_summary, ""]
    if not ep.issues:
        out.append("No issues flagged.")
    for issue in ep.issues:
        out += [f"- **Segment {issue.segment} · {issue.kind}:** \"{issue.excerpt}\"",
                f"  - {issue.explanation}",
                f"  - Fix: {issue.suggested_fix}"]
    return "\n".join(out) + "\n"


def to_json(ep: Episode) -> dict:
    return {
        "figure": ep.figure.slug,
        "topic": ep.topic,
        "plan": ep.plan.model_dump(),
        "script": ep.script.model_dump(),
        "passages": {pid: asdict(p) for pid, p in ep.passages.items()},
        "fact_check": {
            "summary": ep.fact_check_summary,
            "issues": [i.model_dump() for i in ep.issues],
        },
    }


def save(ep: Episode, host_name: str = "Host", output_dir: Path = OUTPUT_DIR) -> Path:
    folder = output_dir / ep.figure.slug / f"{date.today():%Y-%m-%d}-{slugify(ep.topic)}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "script.md").write_text(to_markdown(ep, host_name), encoding="utf-8")
    (folder / "episode.json").write_text(json.dumps(to_json(ep), indent=2, ensure_ascii=False), encoding="utf-8")
    return folder
