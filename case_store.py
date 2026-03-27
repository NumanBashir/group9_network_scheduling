"""Manage locally stored TSN test cases for the project deliverable."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .loader import load_case


LOCAL_TEST_CASES_ROOT = Path(__file__).resolve().parent / "test_cases"
MP2_CASES_ROOT = Path(__file__).resolve().parent / "mp2_cases"
REQUIRED_CASE_FILES = ("topology.json", "streams.json", "routes.json")


def import_case(source_case_directory: str | Path, destination_root: str | Path | None = None, case_name: str | None = None) -> Path:
    source_dir = Path(source_case_directory)
    _validate_case_directory(source_dir)

    destination_base = Path(destination_root) if destination_root is not None else LOCAL_TEST_CASES_ROOT
    destination_base.mkdir(parents=True, exist_ok=True)

    target_dir = destination_base / (case_name or source_dir.name)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    return target_dir


def import_cases(
    source_root: str | Path,
    destination_root: str | Path | None = None,
    pattern: str = "test_case_*",
) -> list[Path]:
    source_root_path = Path(source_root)
    destination_base = Path(destination_root) if destination_root is not None else LOCAL_TEST_CASES_ROOT
    destination_base.mkdir(parents=True, exist_ok=True)

    imported = []
    for candidate in sorted(source_root_path.glob(pattern)):
        if not candidate.is_dir():
            continue
        if _is_case_directory(candidate):
            imported.append(import_case(candidate, destination_root=destination_base))
    return imported


def list_local_cases(root: str | Path | None = None) -> list[Path]:
    case_root = Path(root) if root is not None else LOCAL_TEST_CASES_ROOT
    if not case_root.exists():
        return []
    return sorted(path for path in case_root.iterdir() if path.is_dir() and _is_case_directory(path))


def prepare_mp2_case(
    source_case_directory: str | Path,
    destination_root: str | Path | None = None,
    route_group_index: int = 0,
    case_name: str | None = None,
    bandwidth_mbps: int = 100,
) -> Path:
    source_dir = Path(source_case_directory)
    _validate_case_directory(source_dir)

    case = load_case(source_dir)
    route_groups = case.route_groups
    if route_group_index < 0 or route_group_index >= len(route_groups):
        raise IndexError(f"route_group_index {route_group_index} is out of range for {len(route_groups)} route groups.")

    selected_group = route_groups[route_group_index]
    selected_stream_ids = set(selected_group.stream_ids)

    topology_doc = _load_json(source_dir / "topology.json")
    streams_doc = _load_json(source_dir / "streams.json")
    routes_doc = _load_json(source_dir / "routes.json")

    selected_routes = [route for route in routes_doc["routes"] if int(route["flow_id"]) in selected_stream_ids]
    selected_streams = [stream for stream in streams_doc["streams"] if int(stream["id"]) in selected_stream_ids]
    selected_link_ids = set(selected_group.signature)

    topology = topology_doc["topology"]
    selected_links = [link for link in topology["links"] if str(link["id"]) in selected_link_ids]
    used_nodes = set()
    for link in selected_links:
        used_nodes.add(str(link["source"]))
        used_nodes.add(str(link["destination"]))

    prepared_topology = {
        "topology": {
            "delay_units": topology.get("delay_units", "MICRO_SECOND"),
            "default_bandwidth_mbps": bandwidth_mbps,
            "switches": [switch for switch in topology["switches"] if str(switch["id"]) in used_nodes],
            "end_systems": [end_system for end_system in topology["end_systems"] if str(end_system["id"]) in used_nodes],
            "links": [_rewrite_link_bandwidth(link, bandwidth_mbps) for link in selected_links],
        }
    }
    prepared_streams = {
        "delay_units": streams_doc.get("delay_units", "MICRO_SECOND"),
        "streams": selected_streams,
    }
    prepared_routes = {
        "delay_units": routes_doc.get("delay_units", "MICRO_SECOND"),
        "routes": selected_routes,
    }

    destination_base = Path(destination_root) if destination_root is not None else MP2_CASES_ROOT
    destination_base.mkdir(parents=True, exist_ok=True)
    target_dir = destination_base / (case_name or f"{source_dir.name}_dir{route_group_index + 1}")
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    _write_json(target_dir / "topology.json", prepared_topology)
    _write_json(target_dir / "streams.json", prepared_streams)
    _write_json(target_dir / "routes.json", prepared_routes)
    return target_dir


def prepare_all_local_cases_for_mp2(
    source_root: str | Path | None = None,
    destination_root: str | Path | None = None,
    route_group_index: int = 0,
    bandwidth_mbps: int = 100,
) -> list[Path]:
    source_base = Path(source_root) if source_root is not None else LOCAL_TEST_CASES_ROOT
    prepared = []
    for case_path in list_local_cases(source_base):
        prepared.append(
            prepare_mp2_case(
                source_case_directory=case_path,
                destination_root=destination_root if destination_root is not None else MP2_CASES_ROOT,
                route_group_index=route_group_index,
                case_name=case_path.name,
                bandwidth_mbps=bandwidth_mbps,
            )
        )
    return prepared


def validate_mp2_case(case_directory: str | Path) -> list[str]:
    case = load_case(case_directory)
    issues: list[str] = []

    if len(case.route_groups) != 1:
        issues.append("Case does not have exactly one shared route group.")
    if case.streams:
        bandwidths = {round(link.bandwidth_mbps, 9) for link in case.links}
        if bandwidths != {100.0}:
            issues.append(f"Case link bandwidths are not fixed to 100 Mb/s: {sorted(bandwidths)}")
        queue_classes = {stream.queue_class.value for stream in case.streams}
        if queue_classes != {"A", "B", "BE"}:
            issues.append(f"Case does not contain exactly A/B/BE traffic classes: {sorted(queue_classes)}")
    return issues


def _validate_case_directory(path: Path) -> None:
    if not _is_case_directory(path):
        raise FileNotFoundError(
            f"{path} is not a valid TSN case directory. Expected files: {', '.join(REQUIRED_CASE_FILES)}"
        )


def _is_case_directory(path: Path) -> bool:
    return path.is_dir() and all((path / file_name).exists() for file_name in REQUIRED_CASE_FILES)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _rewrite_link_bandwidth(link: dict, bandwidth_mbps: int) -> dict:
    updated = dict(link)
    updated["bandwidth_mbps"] = bandwidth_mbps
    return updated
