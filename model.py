"""Core domain objects shared by the analytical and simulation engines."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class QueueClass(str, Enum):
    A = "A"
    B = "B"
    BE = "BE"


@dataclass(frozen=True)
class TopologyLink:
    id: str
    source: str
    source_port: int
    destination: str
    destination_port: int
    bandwidth_mbps: float
    propagation_delay_us: float


@dataclass(frozen=True)
class StreamHop:
    link_id: str
    source: str
    source_port: int
    destination: str
    destination_port: int
    bandwidth_mbps: float
    propagation_delay_us: float
    transmission_time_us: float

    @property
    def total_latency_us(self) -> float:
        return self.propagation_delay_us + self.transmission_time_us


@dataclass(frozen=True)
class StreamSpec:
    stream_id: int
    name: str
    source: str
    destination: str
    queue_class: QueueClass
    pcp: int
    size_bytes: int
    period_us: float
    deadline_us: float
    hops: tuple[StreamHop, ...]

    @property
    def route_signature(self) -> tuple[str, ...]:
        return tuple(hop.link_id for hop in self.hops)

    @property
    def hop_count(self) -> int:
        return len(self.hops)

    @property
    def end_to_end_transmission_time_us(self) -> float:
        return sum(hop.transmission_time_us for hop in self.hops)

    @property
    def end_to_end_propagation_delay_us(self) -> float:
        return sum(hop.propagation_delay_us for hop in self.hops)

    @property
    def minimum_link_latency_us(self) -> float:
        return sum(hop.total_latency_us for hop in self.hops)


@dataclass(frozen=True)
class RouteGroup:
    signature: tuple[str, ...]
    streams: tuple[StreamSpec, ...]

    @property
    def hop_count(self) -> int:
        return len(self.signature)

    @property
    def queue_counts(self) -> dict[str, int]:
        counts = Counter(stream.queue_class.value for stream in self.streams)
        return {queue_name: counts.get(queue_name, 0) for queue_name in ("A", "B", "BE")}

    @property
    def stream_ids(self) -> tuple[int, ...]:
        return tuple(stream.stream_id for stream in self.streams)


@dataclass(frozen=True)
class NetworkCase:
    case_directory: Path
    topology_path: Path
    streams_path: Path
    routes_path: Path
    links: tuple[TopologyLink, ...]
    streams: tuple[StreamSpec, ...]

    @property
    def queue_counts(self) -> dict[str, int]:
        counts = Counter(stream.queue_class.value for stream in self.streams)
        return {queue_name: counts.get(queue_name, 0) for queue_name in ("A", "B", "BE")}

    @property
    def route_groups(self) -> tuple[RouteGroup, ...]:
        grouped: dict[tuple[str, ...], list[StreamSpec]] = defaultdict(list)
        for stream in self.streams:
            grouped[stream.route_signature].append(stream)
        groups = [
            RouteGroup(signature=signature, streams=tuple(sorted(group, key=lambda stream: stream.stream_id)))
            for signature, group in grouped.items()
        ]
        return tuple(sorted(groups, key=lambda group: (group.signature, group.stream_ids)))

    @property
    def has_single_shared_route(self) -> bool:
        return len(self.route_groups) == 1

