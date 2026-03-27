"""Small CLI for inspecting normalized TSN cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analysis import analyze_case
from .case_store import LOCAL_TEST_CASES_ROOT, import_case, import_cases, list_local_cases
from .loader import load_case
from .reference import load_reference_wcrts
from .simulation import simulate_case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="group9-network-scheduling")
    subparsers = parser.add_subparsers(dest="command")

    summarize_parser = subparsers.add_parser("summarize", help="Load a TSN test case and print a summary.")
    summarize_parser.add_argument("case_directory", type=Path)
    summarize_parser.add_argument("--json", action="store_true", dest="as_json")

    import_case_parser = subparsers.add_parser("import-case", help="Copy a TSN case into the local project case store.")
    import_case_parser.add_argument("source_case_directory", type=Path)
    import_case_parser.add_argument("--name", dest="case_name")

    import_cases_parser = subparsers.add_parser("import-cases", help="Copy multiple generated TSN cases into the local project case store.")
    import_cases_parser.add_argument("source_root", type=Path)
    import_cases_parser.add_argument("--pattern", default="test_case_*")

    subparsers.add_parser("list-cases", help="List locally stored test cases.")

    analyze_parser = subparsers.add_parser("analyze", help="Run the analytical CBS bound on a TSN case.")
    analyze_parser.add_argument("case_directory", type=Path)
    analyze_parser.add_argument("--json", action="store_true", dest="as_json")

    simulate_parser = subparsers.add_parser("simulate", help="Run the event-driven CBS simulator on a TSN case.")
    simulate_parser.add_argument("case_directory", type=Path)
    simulate_parser.add_argument("--cycles", type=int, default=5)
    simulate_parser.add_argument("--json", action="store_true", dest="as_json")

    compare_parser = subparsers.add_parser("compare", help="Run analysis and simulation and compare them.")
    compare_parser.add_argument("case_directory", type=Path)
    compare_parser.add_argument("--cycles", type=int, default=5)
    compare_parser.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args(argv)
    if args.command == "summarize":
        return _summarize_command(case_directory=args.case_directory, as_json=args.as_json)
    if args.command == "import-case":
        return _import_case_command(source_case_directory=args.source_case_directory, case_name=args.case_name)
    if args.command == "import-cases":
        return _import_cases_command(source_root=args.source_root, pattern=args.pattern)
    if args.command == "list-cases":
        return _list_cases_command()
    if args.command == "analyze":
        return _analyze_command(case_directory=args.case_directory, as_json=args.as_json)
    if args.command == "simulate":
        return _simulate_command(case_directory=args.case_directory, cycles=args.cycles, as_json=args.as_json)
    if args.command == "compare":
        return _compare_command(case_directory=args.case_directory, cycles=args.cycles, as_json=args.as_json)

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


def _import_case_command(source_case_directory: Path, case_name: str | None) -> int:
    target = import_case(source_case_directory, case_name=case_name)
    print(f"Imported case to: {target}")
    return 0


def _import_cases_command(source_root: Path, pattern: str) -> int:
    imported = import_cases(source_root=source_root, pattern=pattern)
    print(f"Imported {len(imported)} case(s) into: {LOCAL_TEST_CASES_ROOT}")
    for path in imported:
        print(f"  - {path}")
    return 0


def _list_cases_command() -> int:
    cases = list_local_cases()
    print(f"Local case store: {LOCAL_TEST_CASES_ROOT}")
    for case_path in cases:
        print(f"  - {case_path}")
    return 0


def _analyze_command(case_directory: Path, as_json: bool) -> int:
    case = load_case(case_directory)
    analysis = analyze_case(case)
    payload = _build_analysis_payload(case_directory, analysis)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    _print_stream_table(
        title=f"Analytical CBS bounds for {case_directory}",
        stream_rows=payload["streams"],
        value_key="analytical_pure_wcd_us",
    )
    return 0


def _simulate_command(case_directory: Path, cycles: int, as_json: bool) -> int:
    case = load_case(case_directory)
    simulation = simulate_case(case, cycles=cycles)
    payload = _build_simulation_payload(case_directory, simulation)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    _print_stream_table(
        title=f"Simulated CBS delays for {case_directory}",
        stream_rows=payload["streams"],
        value_key="observed_pure_wcd_us",
    )
    return 0


def _compare_command(case_directory: Path, cycles: int, as_json: bool) -> int:
    case = load_case(case_directory)
    analysis = analyze_case(case)
    simulation = simulate_case(case, cycles=cycles)
    reference = load_reference_wcrts(case_directory)

    rows = []
    for stream in case.streams:
        analysis_row = analysis.by_stream_id[stream.stream_id]
        simulation_row = simulation.by_stream_id[stream.stream_id]
        analytical_pure = analysis_row.pure_wcd_us
        observed_pure = simulation_row.observed_pure_wcd_us
        reference_pure = reference.get(stream.stream_id)
        rows.append(
            {
                "stream_id": stream.stream_id,
                "queue_class": stream.queue_class.value,
                "analytical_supported": analysis_row.supported,
                "analysis_reason": analysis_row.reason,
                "analytical_pure_wcd_us": analytical_pure,
                "analytical_delivery_wcd_us": analysis_row.delivery_wcd_us,
                "observed_pure_wcd_us": observed_pure,
                "observed_delivery_wcd_us": simulation_row.observed_delivery_wcd_us,
                "frame_instances": simulation_row.frame_instances,
                "reference_wcrt_us": reference_pure,
                "simulation_minus_analysis_us": None if analytical_pure is None else observed_pure - analytical_pure,
                "analysis_minus_reference_us": None if reference_pure is None or analytical_pure is None else analytical_pure - reference_pure,
            }
        )

    payload = {
        "case_directory": str(case_directory),
        "cycles": cycles,
        "streams": rows,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    _print_stream_table(
        title=f"Analysis vs simulation for {case_directory}",
        stream_rows=rows,
        value_key="analytical_pure_wcd_us",
        secondary_key="observed_pure_wcd_us",
        tertiary_key="reference_wcrt_us",
    )
    return 0


def _build_analysis_payload(case_directory: Path, analysis) -> dict:
    return {
        "case_directory": str(case_directory),
        "streams": [
            {
                "stream_id": stream_id,
                "queue_class": stream_analysis.queue_class.value,
                "supported": stream_analysis.supported,
                "reason": stream_analysis.reason,
                "analytical_pure_wcd_us": stream_analysis.pure_wcd_us,
                "analytical_delivery_wcd_us": stream_analysis.delivery_wcd_us,
            }
            for stream_id, stream_analysis in sorted(analysis.by_stream_id.items())
        ],
    }


def _build_simulation_payload(case_directory: Path, simulation) -> dict:
    return {
        "case_directory": str(case_directory),
        "simulated_until_us": simulation.simulated_until_us,
        "streams": [
            {
                "stream_id": stream_id,
                "queue_class": stream_simulation.queue_class.value,
                "observed_pure_wcd_us": stream_simulation.observed_pure_wcd_us,
                "observed_delivery_wcd_us": stream_simulation.observed_delivery_wcd_us,
                "frame_instances": stream_simulation.frame_instances,
            }
            for stream_id, stream_simulation in sorted(simulation.by_stream_id.items())
        ],
    }


def _print_stream_table(
    title: str,
    stream_rows: list[dict],
    value_key: str,
    secondary_key: str | None = None,
    tertiary_key: str | None = None,
) -> None:
    print(title)
    for row in stream_rows:
        parts = [
            f"stream={row['stream_id']}",
            f"class={row['queue_class']}",
            f"{value_key}={_format_value(row.get(value_key))}",
        ]
        if secondary_key is not None:
            parts.append(f"{secondary_key}={_format_value(row.get(secondary_key))}")
        if tertiary_key is not None:
            parts.append(f"{tertiary_key}={_format_value(row.get(tertiary_key))}")
        if row.get("analysis_reason"):
            parts.append(f"reason={row['analysis_reason']}")
        print("  " + " | ".join(parts))


def _format_value(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)
