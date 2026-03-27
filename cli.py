"""Small CLI for inspecting normalized TSN cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .loader import load_case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="group9-network-scheduling")
    subparsers = parser.add_subparsers(dest="command")

    summarize_parser = subparsers.add_parser("summarize", help="Load a TSN test case and print a summary.")
    summarize_parser.add_argument("case_directory", type=Path)
    summarize_parser.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args(argv)
    if args.command == "summarize":
        return _summarize_command(case_directory=args.case_directory, as_json=args.as_json)

    parser.print_help()
    return 1


def _summarize_command(case_directory: Path, as_json: bool) -> int:
    case = load_case(case_directory)
    summary = {
        "case_directory": str(case.case_directory),
        "stream_count": len(case.streams),
        "link_count": len(case.links),
        "queue_counts": case.queue_counts,
        "route_group_count": len(case.route_groups),
        "has_single_shared_route": case.has_single_shared_route,
        "route_groups": [
            {
                "signature": list(group.signature),
                "hop_count": group.hop_count,
                "stream_ids": list(group.stream_ids),
                "queue_counts": group.queue_counts,
            }
            for group in case.route_groups
        ],
    }

    if as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    print(f"Case: {summary['case_directory']}")
    print(f"Streams: {summary['stream_count']} | Links: {summary['link_count']}")
    print(
        "Queues: "
        f"A={summary['queue_counts']['A']} "
        f"B={summary['queue_counts']['B']} "
        f"BE={summary['queue_counts']['BE']}"
    )
    print(
        "Route groups: "
        f"{summary['route_group_count']} | Single shared route: {summary['has_single_shared_route']}"
    )
    for index, group in enumerate(summary["route_groups"], start=1):
        print(
            f"  [{index}] hops={group['hop_count']} signature={group['signature']} "
            f"streams={group['stream_ids']} queues={group['queue_counts']}"
        )
    return 0

