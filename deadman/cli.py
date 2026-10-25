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
    for passage, score in index.search(args.query, k=args.k):
        print(f"\n[{passage.id}] {score:.1f}  {passage.citation()}")
        print(f"  {passage.text[:400]}{'...' if len(passage.text) > 400 else ''}")


def cmd_script(args: argparse.Namespace) -> None:
    import anthropic

    from .render import save
    from .script import GenerationError, generate_episode

    figure = load_figure(args.figure)
    index = BM25Index(load_passages(figure))
    client = anthropic.Anthropic()
    try:
        episode = generate_episode(
            client, figure, index, args.topic,
            minutes=args.minutes, n_questions=args.questions,
            host_name=args.host, run_fact_check=not args.no_fact_check,
        )
    except (GenerationError, anthropic.APIError) as e:
        sys.exit(f"Error: {e}")
    except TypeError as e:
        if "authentication" not in str(e):
            raise
        sys.exit("Error: no Anthropic credentials found. Set ANTHROPIC_API_KEY or run `ant auth login`.")
    folder = save(episode, host_name=args.host)
    print(f"Wrote {folder / 'script.md'}")
    if episode.issues:
        print(f"{len(episode.issues)} fact-check issue(s) flagged; review them before recording.")


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
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("script", help="Generate a sourced episode script")
    p.add_argument("figure")
    p.add_argument("topic", help='e.g. "Would Adam Smith approve of Amazon?"')
    p.add_argument("--minutes", type=int, default=10, help="Target episode length")
    p.add_argument("--questions", type=int, default=6, help="Number of host questions")
    p.add_argument("--host", default="Host", help="Host name used in the script")
    p.add_argument("--no-fact-check", action="store_true", help="Skip the model fact-check pass")
    p.set_defaults(func=cmd_script)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except FileNotFoundError as e:
        sys.exit(f"Error: {e}")
