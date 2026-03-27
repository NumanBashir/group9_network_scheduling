"""Load TSN generator outputs into a normalized in-memory model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .model import NetworkCase, QueueClass, StreamHop, StreamSpec, TopologyLink
from .units import to_microseconds, transmission_time_us


@dataclass(frozen=True)
class PriorityMap:
    class_a_pcps: frozenset[int] = frozenset({2})
    class_b_pcps: frozenset[int] = frozenset({1})
    best_effort_pcps: frozenset[int] = frozenset({0})

    def classify(self, raw_stream: dict) -> QueueClass:
        for key in ("queue_class", "avb_class", "class"):
            raw_value = raw_stream.get(key)
            if raw_value is None:
                continue
            normalized = str(raw_value).strip().upper().replace("AVB_", "").replace("CLASS_", "")
            if normalized in {"A", "B", "BE"}:
                return QueueClass(normalized)
            raise ValueError(
                f"Unsupported explicit queue class {raw_value!r} for stream {raw_stream.get('id')}."
            )

        pcp = int(raw_stream["PCP"])
        if pcp in self.class_a_pcps:
            return QueueClass.A
        if pcp in self.class_b_pcps:
            return QueueClass.B
        if pcp in self.best_effort_pcps:
            return QueueClass.BE
        raise ValueError(
            f"PCP {pcp} is not mapped to A, B, or BE. Override PriorityMap for this test case."
        )


def load_case(case_directory: str | Path, priority_map: PriorityMap | None = None) -> NetworkCase:
    case_dir = Path(case_directory)
    topology_path = case_dir / "topology.json"
    streams_path = case_dir / "streams.json"
    routes_path = case_dir / "routes.json"

    topology_doc = _load_json(topology_path)
    streams_doc = _load_json(streams_path)
    routes_doc = _load_json(routes_path)

    links = _load_links(topology_doc)
    link_lookup = _build_link_lookup(links)
    route_lookup = {int(route["flow_id"]): route for route in routes_doc["routes"]}
    mapping = priority_map or PriorityMap()

    stream_specs = []
    for raw_stream in streams_doc["streams"]:
        stream_specs.append(
            _normalize_stream(
                raw_stream=raw_stream,
                streams_unit=streams_doc.get("delay_units"),
                route_entry=route_lookup[int(raw_stream["id"])],
                link_lookup=link_lookup,
                priority_map=mapping,
            )
        )

    return NetworkCase(
        case_directory=case_dir,
        topology_path=topology_path,
        streams_path=streams_path,
        routes_path=routes_path,
        links=tuple(links),
        streams=tuple(sorted(stream_specs, key=lambda stream: stream.stream_id)),
    )


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required TSN file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_links(topology_doc: dict) -> list[TopologyLink]:
    topology = topology_doc["topology"]
    delay_unit = topology.get("delay_units")
    default_bandwidth = float(topology.get("default_bandwidth_mbps", 100.0))
    return [
        TopologyLink(
            id=str(raw_link["id"]),
            source=str(raw_link["source"]),
            source_port=int(raw_link["sourcePort"]),
            destination=str(raw_link["destination"]),
            destination_port=int(raw_link["destinationPort"]),
            bandwidth_mbps=float(raw_link.get("bandwidth_mbps", default_bandwidth)),
            propagation_delay_us=to_microseconds(raw_link.get("delay", 0.0), delay_unit),
        )
        for raw_link in topology["links"]
    ]


def _build_link_lookup(links: list[TopologyLink]) -> dict[tuple[str, int, str], TopologyLink]:
    lookup: dict[tuple[str, int, str], TopologyLink] = {}
    for link in links:
        key = (link.source, link.source_port, link.destination)
        if key in lookup:
            raise ValueError(f"Ambiguous parallel link for lookup key {key}.")
        lookup[key] = link
    return lookup


def _normalize_stream(
    raw_stream: dict,
    streams_unit: str | None,
    route_entry: dict,
    link_lookup: dict[tuple[str, int, str], TopologyLink],
    priority_map: PriorityMap,
) -> StreamSpec:
    destinations = raw_stream["destinations"]
    if len(destinations) != 1:
        raise ValueError(
            f"Mini-project 2 loader currently supports unicast streams only, got {len(destinations)}"
            f" destinations for stream {raw_stream['id']}."
        )
    if int(raw_stream.get("redundancy", 0)) != 0:
        raise ValueError(f"Redundant routes are not supported in the simplified MP2 loader.")
    if len(route_entry["paths"]) != 1:
        raise ValueError(
            f"Mini-project 2 loader currently supports a single path per stream, got {len(route_entry['paths'])}"
            f" paths for stream {raw_stream['id']}."
        )

    destination = destinations[0]
    path = route_entry["paths"][0]
    if path[0]["node"] != raw_stream["source"]:
        raise ValueError(f"Route for stream {raw_stream['id']} does not start at the declared source.")
    if path[-1]["node"] != destination["id"]:
        raise ValueError(f"Route for stream {raw_stream['id']} does not end at the declared destination.")

    size_bytes = int(raw_stream["size"])
    hops = []
    for current_node, next_node in zip(path, path[1:]):
        lookup_key = (str(current_node["node"]), int(current_node["port"]), str(next_node["node"]))
        try:
            link = link_lookup[lookup_key]
        except KeyError as exc:
            raise ValueError(
                f"Unable to resolve route hop {lookup_key} for stream {raw_stream['id']}."
            ) from exc
        hops.append(
            StreamHop(
                link_id=link.id,
                source=link.source,
                source_port=link.source_port,
                destination=link.destination,
                destination_port=link.destination_port,
                bandwidth_mbps=link.bandwidth_mbps,
                propagation_delay_us=link.propagation_delay_us,
                transmission_time_us=transmission_time_us(size_bytes=size_bytes, bandwidth_mbps=link.bandwidth_mbps),
            )
        )

    return StreamSpec(
        stream_id=int(raw_stream["id"]),
        name=str(raw_stream["name"]),
        source=str(raw_stream["source"]),
        destination=str(destination["id"]),
        queue_class=priority_map.classify(raw_stream),
        pcp=int(raw_stream["PCP"]),
        size_bytes=size_bytes,
        period_us=to_microseconds(raw_stream["period"], streams_unit),
        deadline_us=to_microseconds(destination["deadline"], streams_unit),
        hops=tuple(hops),
    )
