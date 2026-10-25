"""Command-line entry point: python -m deadman <command> ..."""

from __future__ import annotations

import argparse
import sys

from .figures import load_figure
from .retrieval import BM25Index
from .sources import ingest, load_passages


def cmd_ingest(args: argparse.Namespace) -> None:
    figure = load_figure(args.figure)
    passages = ingest(figure, force=args.force)
    by_source: dict[str, int] = {}
    for p in passages:
        by_source[p.title] = by_source.get(p.title, 0) + 1
    for title, n in by_source.items():
        print(f"  {n:5d} passages  {title}")
    print(f"Indexed {len(passages)} passages for {figure.name}.")


def cmd_search(args: argparse.Namespace) -> None:
    figure = load_figure(args.figure)
    index = BM25Index(load_passages(figure))
    passages = [p for p in index.passages if not args.kind or p.kind == args.kind]
    if args.kind:
        index = BM25Index(passages)
    for passage, score in index.search(args.query, k=args.k):
        print(f"\n[{passage.id}] {score:.1f}  {passage.citation()} ({passage.kind})")
        print(f"  {passage.text[:400]}{'...' if len(passage.text) > 400 else ''}")


def cmd_show(args: argparse.Namespace) -> None:
    figure = load_figure(args.figure)
    by_id = {p.id: p for p in load_passages(figure)}
    for pid in args.ids:
        if pid not in by_id:
            sys.exit(f"Error: no passage {pid!r}")
        p = by_id[pid]
        print(f"### {p.id} ({p.kind}) {p.citation()}\n\n{p.text}\n")


def cmd_new(args: argparse.Namespace) -> None:
    from .episodes import new_episode

    folder = new_episode(load_figure(args.figure), args.host, args.format, args.themes, args.slug)
    print(f"Created {folder}")
    print("Next: research into research.md, write transcript.md, then `python -m deadman check "
          f"{folder.name[:3]}`.")


def _print_report(report) -> None:
    for issue in report.errors:
        print(f"ERROR   segment {issue.segment} · {issue.kind}: {issue.explanation} ({issue.excerpt[:60]!r})")
    for warning in report.warnings:
        print(f"warning {warning}")
    minutes = report.words / 150
    target = f" of ~{report.target_words:,} target" if report.target_words else ""
    print(f"{report.words:,} words{target} (~{minutes:.0f} min). "
          f"{len(report.errors)} error(s), {len(report.warnings)} warning(s).")


def cmd_check(args: argparse.Namespace) -> None:
    from .episodes import check_episode, load_episode, resolve_folder

    episode, brief = load_episode(resolve_folder(args.episode))
    report = check_episode(episode, brief)
    _print_report(report)
    if report.errors:
        sys.exit(1)


def cmd_render(args: argparse.Namespace) -> None:
    from .episodes import check_episode, load_episode, resolve_folder
    from .render import save

    from .audio import load_timings

    folder = resolve_folder(args.episode)
    episode, brief = load_episode(folder)
    timings = load_timings(folder, episode)
    # Silent placeholder audio only approximates timing; never publish timestamps from it.
    episode.timings = timings if timings and timings["engine"] != "placeholder" else None
    report = check_episode(episode, brief)
    _print_report(report)
    if report.errors and not args.force:
        sys.exit("Not rendered: fix the errors above, or pass --force to render anyway.")
    episode.issues = report.errors
    review = folder / "review.md"
    episode.fact_check_summary = (
        "See review.md for the fact-checker's line-by-line review." if review.exists()
        else "No review.md yet: run the fact-checker before publishing."
    )
    save(episode, brief.host, folder)
    print(f"Rendered {folder / 'script.md'}")


def cmd_audio(args: argparse.Namespace) -> None:
    from .audio import AudioError, ElevenLabs, Placeholder, build_audio, estimate, load_studio, voices_for
    from .episodes import load_episode, resolve_folder

    folder = resolve_folder(args.episode)
    episode, brief = load_episode(folder)
    studio = load_studio()
    model_id = studio["audio"]["model_id"]
    voices = voices_for(episode.figure, studio)
    if args.estimate:
        e = estimate(episode, folder, voices, model_id)
        print(f"{e['lines']} lines, {e['characters']:,} characters in total; "
              f"{e['new_characters']:,} characters not yet voiced.")
        print("ElevenLabs bills by character: compare with your plan's monthly character quota.")
        return
    try:
        engine = Placeholder() if args.placeholder else ElevenLabs(model_id, studio["audio"]["output_format"])
        timings = build_audio(episode, folder, engine, voices, studio)
    except AudioError as e:
        sys.exit(f"Error: {e}")
    minutes, seconds = divmod(round(timings["duration"]), 60)
    print(f"Wrote {folder / 'audio' / 'episode.mp3'} ({minutes}:{seconds:02d}) and captions.srt")
    if args.placeholder:
        print("Placeholder audio is silent; it only sets timing for building and testing video.")
    print(f"Run `python -m deadman render {brief.number}` to update chapter timestamps.")


def cmd_placeholders(args: argparse.Namespace) -> None:
    from .audio import load_studio
    from .video import make_placeholders

    made = make_placeholders(load_figure(args.figure), load_studio())
    for path in made:
        print(f"Created placeholder {path}")
    if not made:
        print("All studio assets already exist; nothing to do.")


def cmd_video(args: argparse.Namespace) -> None:
    from .audio import load_studio, load_timings
    from .episodes import load_episode, resolve_folder
    from .video import VideoError, build_video, placeholder_assets

    folder = resolve_folder(args.episode)
    episode, brief = load_episode(folder)
    timings = load_timings(folder, episode)
    if timings is None:
        sys.exit(f"Error: no current audio. Run `python -m deadman audio {brief.number}` first "
                 "(add --placeholder to test without voices).")
    studio = load_studio()
    for path in placeholder_assets(episode, studio):
        print(f"warning: still using placeholder art {path} (see show/studio.md)")
    if timings["engine"] == "placeholder":
        print("warning: audio is a silent placeholder; run `deadman audio` with ElevenLabs for the real episode")
    try:
        out = build_video(episode, folder, timings, studio, preview=args.preview, scale=args.scale)
    except VideoError as e:
        sys.exit(f"Error: {e}")
    print(f"Wrote {out}")


def _generate(args: argparse.Namespace, fmt_name: str, build) -> None:
    """Create an episode folder, generate the episode with the API, and write its files."""
    import anthropic

    from .episodes import Brief, new_episode, save_episode_files, write_brief
    from .render import save
    from .script import GenerationError

    figure = load_figure(args.figure)
    index = BM25Index(load_passages(figure))
    try:
        episode = build(anthropic.Anthropic(), figure, index)
    except (GenerationError, anthropic.APIError) as e:
        sys.exit(f"Error: {e}")
    except TypeError as e:
        if "authentication" not in str(e):
            raise
        sys.exit("Error: no Anthropic credentials found. Set ANTHROPIC_API_KEY or run `ant auth login`.")

    folder = new_episode(figure, args.host, fmt_name or "longform", episode.topic, episode.title)
    if not fmt_name:
        brief_path = folder / "brief.toml"
        number = int(folder.name[:3])
        brief_path.write_text(write_brief(Brief(number, figure.slug, args.host, "", episode.topic)), encoding="utf-8")
    save_episode_files(episode, folder, args.host)
    if episode.issues:
        (folder / "review.md").write_text(
            "# Review (generated)\n\n" + episode.fact_check_summary + "\n\n" + "\n".join(
                f"- Segment {i.segment} · {i.kind}: {i.explanation} Fix: {i.suggested_fix}" for i in episode.issues
            ) + "\n", encoding="utf-8")
    save(episode, args.host, folder)
    print(f"Wrote {folder}")
    if episode.issues:
        print(f"{len(episode.issues)} fact-check issue(s) flagged; see review.md before recording.")


def cmd_script(args: argparse.Namespace) -> None:
    from .script import generate_episode

    _generate(args, "", lambda client, figure, index: generate_episode(
        client, figure, index, args.topic, minutes=args.minutes, n_questions=args.questions,
        host_name=args.host, run_fact_check=not args.no_fact_check,
    ))


def cmd_episode(args: argparse.Namespace) -> None:
    from .longform import generate_longform, load_format

    from dataclasses import replace

    from .episodes import pending_question

    fmt = load_format(args.format)
    if asked := pending_question():
        fmt = replace(fmt, tradition=f"{fmt.tradition}\nThe previous guest, {asked[0]}, left this question, which "
                                     f"the host reads out in the last chapter for this guest to answer: {asked[1]}")
    _generate(args, args.format, lambda client, figure, index: generate_longform(
        client, figure, index, fmt, themes=args.themes,
        host_name=args.host, run_fact_check=not args.no_fact_check,
    ))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="deadman", description="The Deadman Show script pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="Download and index a figure's writings")
    p.add_argument("figure", help="Figure slug, e.g. adam_smith")
    p.add_argument("--force", action="store_true", help="Re-download source texts")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("search", help="Search a figure's indexed writings")
    p.add_argument("figure")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5, help="Number of results")
    p.add_argument("--kind", choices=["primary", "biography"], help="Only search one kind of source")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("show", help="Print passages in full by id")
    p.add_argument("figure")
    p.add_argument("ids", nargs="+", help="Passage ids, e.g. won-0004 rae-0003")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("new", help="Create a new episode folder")
    p.add_argument("figure")
    p.add_argument("--host", required=True, help="Host name, e.g. Ram")
    p.add_argument("--format", default="longform", help="Show format in formats/ (default: longform)")
    p.add_argument("--themes", default="", help='Topics to make sure are covered, e.g. "AI, India"')
    p.add_argument("--slug", default="", help="Short name for the folder, e.g. adam-smith-longform")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("check", help="Check an episode's transcript without a model")
    p.add_argument("episode", help="Episode number, folder name or path")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("render", help="Check an episode and write script.md, description and JSON")
    p.add_argument("episode", help="Episode number, folder name or path")
    p.add_argument("--force", action="store_true", help="Render even if checks report errors")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("audio", help="Voice an episode with ElevenLabs (needs ELEVENLABS_API_KEY)")
    p.add_argument("episode", help="Episode number, folder name or path")
    p.add_argument("--estimate", action="store_true", help="Only count characters to voice; spends nothing")
    p.add_argument("--placeholder", action="store_true",
                   help="Silent audio timed like speech, to build and test video without voices")
    p.set_defaults(func=cmd_audio)

    p = sub.add_parser("placeholders", help="Create stand-in studio and portrait images for missing assets")
    p.add_argument("figure", help="Guest whose portrait to create if missing")
    p.set_defaults(func=cmd_placeholders)

    p = sub.add_parser("video", help="Assemble the episode video in the studio (after `audio`)")
    p.add_argument("episode", help="Episode number, folder name or path")
    p.add_argument("--preview", type=int, default=0, metavar="N", help="Only the first N lines, fast")
    p.add_argument("--scale", type=float, default=1.0, help="Render size, e.g. 0.5 for a quick 960x540 draft")
    p.set_defaults(func=cmd_video)

    p = sub.add_parser("script", help="[API] Generate a short single-topic episode")
    p.add_argument("figure")
    p.add_argument("topic", help='e.g. "Would Adam Smith approve of Amazon?"')
    p.add_argument("--minutes", type=int, default=10, help="Target episode length")
    p.add_argument("--questions", type=int, default=6, help="Number of host questions")
    p.add_argument("--host", default="Host", help="Host name used in the script")
    p.add_argument("--no-fact-check", action="store_true", help="Skip the model fact-check pass")
    p.set_defaults(func=cmd_script)

    p = sub.add_parser("episode", help="[API] Generate a long-form, multi-chapter episode")
    p.add_argument("figure")
    p.add_argument("--format", default="longform", help="Show format in formats/ (default: longform)")
    p.add_argument("--themes", default="", help='Topics to make sure are covered, e.g. "AI, India, startups"')
    p.add_argument("--host", default="Host", help="Host name used in the script")
    p.add_argument("--no-fact-check", action="store_true", help="Skip the model fact-check pass")
    p.set_defaults(func=cmd_episode)

    args = parser.parse_args(argv)
    from .episodes import EpisodeFileError

    try:
        args.func(args)
    except (FileNotFoundError, EpisodeFileError) as e:
        sys.exit(f"Error: {e}")
