"""Analytical CBS delay bounds for the simplified mini-project model."""

from __future__ import annotations

from dataclasses import dataclass

from .model import NetworkCase, QueueClass, RouteGroup, StreamSpec


@dataclass(frozen=True)
class HopAnalysis:
    hop_index: int
    link_id: str
    transmission_time_us: float
    same_class_delay_us: float
    mixed_interference_delay_us: float
    pure_wcd_us: float
    propagation_delay_us: float
    delivery_wcd_us: float


@dataclass(frozen=True)
class StreamAnalysis:
    stream_id: int
    queue_class: QueueClass
    supported: bool
    reason: str | None
    hop_analyses: tuple[HopAnalysis, ...]
    pure_wcd_us: float | None
    delivery_wcd_us: float | None


@dataclass(frozen=True)
class RouteGroupAnalysis:
    signature: tuple[str, ...]
    stream_ids: tuple[int, ...]
    analyses: tuple[StreamAnalysis, ...]


@dataclass(frozen=True)
class AnalysisResult:
    route_groups: tuple[RouteGroupAnalysis, ...]

    @property
    def by_stream_id(self) -> dict[int, StreamAnalysis]:
        return {
            analysis.stream_id: analysis
            for group in self.route_groups
            for analysis in group.analyses
        }


def analyze_case(
    case: NetworkCase,
    idle_slope_fraction: float = 0.5,
    send_slope_fraction: float = 0.5,
) -> AnalysisResult:
    if idle_slope_fraction <= 0 or send_slope_fraction <= 0:
        raise ValueError("idle_slope_fraction and send_slope_fraction must be positive.")

    route_group_results = []
    for route_group in case.route_groups:
        route_group_results.append(
            RouteGroupAnalysis(
                signature=route_group.signature,
                stream_ids=route_group.stream_ids,
                analyses=_analyze_route_group(
                    route_group=route_group,
                    idle_slope_fraction=idle_slope_fraction,
                    send_slope_fraction=send_slope_fraction,
                ),
            )
        )
    return AnalysisResult(route_groups=tuple(route_group_results))


def _analyze_route_group(
    route_group: RouteGroup,
    idle_slope_fraction: float,
    send_slope_fraction: float,
) -> tuple[StreamAnalysis, ...]:
    scale_factor = 1.0 + (send_slope_fraction / idle_slope_fraction)
    higher_class_penalty_factor = 1.0 + (idle_slope_fraction / send_slope_fraction)

    class_to_streams = {
        queue_class: tuple(stream for stream in route_group.streams if stream.queue_class == queue_class)
        for queue_class in QueueClass
    }
    hop_count = route_group.hop_count

    max_transmission_by_class_and_hop = {
        queue_class: [
            max(
                (stream.hops[hop_index].transmission_time_us for stream in class_to_streams[queue_class]),
                default=0.0,
            )
            for hop_index in range(hop_count)
        ]
        for queue_class in QueueClass
    }

    analyses = []
    for stream in route_group.streams:
        if stream.queue_class == QueueClass.BE:
            analyses.append(
                StreamAnalysis(
                    stream_id=stream.stream_id,
                    queue_class=stream.queue_class,
                    supported=False,
                    reason="Analytical CBS bound is implemented for AVB classes A and B only.",
                    hop_analyses=tuple(),
                    pure_wcd_us=None,
                    delivery_wcd_us=None,
                )
            )
            continue

        hop_analyses = []
        same_class_streams = class_to_streams[stream.queue_class]
        for hop_index, hop in enumerate(stream.hops):
            same_class_delay = sum(
                other_stream.hops[hop_index].transmission_time_us * scale_factor
                for other_stream in same_class_streams
                if other_stream.stream_id != stream.stream_id
            )
            if stream.queue_class == QueueClass.A:
                mixed_interference = max(
                    max_transmission_by_class_and_hop[QueueClass.B][hop_index],
                    max_transmission_by_class_and_hop[QueueClass.BE][hop_index],
                )
            else:
                mixed_interference = (
                    max_transmission_by_class_and_hop[QueueClass.BE][hop_index] * higher_class_penalty_factor
                    + max_transmission_by_class_and_hop[QueueClass.A][hop_index]
                )

            pure_wcd_us = hop.transmission_time_us + same_class_delay + mixed_interference
            hop_analyses.append(
                HopAnalysis(
                    hop_index=hop_index,
                    link_id=hop.link_id,
                    transmission_time_us=hop.transmission_time_us,
                    same_class_delay_us=same_class_delay,
                    mixed_interference_delay_us=mixed_interference,
                    pure_wcd_us=pure_wcd_us,
                    propagation_delay_us=hop.propagation_delay_us,
                    delivery_wcd_us=pure_wcd_us + hop.propagation_delay_us,
                )
            )

        analyses.append(
            StreamAnalysis(
                stream_id=stream.stream_id,
                queue_class=stream.queue_class,
                supported=True,
                reason=None,
                hop_analyses=tuple(hop_analyses),
                pure_wcd_us=sum(hop_result.pure_wcd_us for hop_result in hop_analyses),
                delivery_wcd_us=sum(hop_result.delivery_wcd_us for hop_result in hop_analyses),
            )
        )

    return tuple(sorted(analyses, key=lambda analysis: analysis.stream_id))

