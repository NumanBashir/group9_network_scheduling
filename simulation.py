"""Event-driven simulator for the simplified TSN/CBS mini-project model."""

from __future__ import annotations

import heapq
import itertools
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .model import NetworkCase, QueueClass, RouteGroup, StreamSpec


EPSILON = 1e-9


@dataclass
class _FrameInstance:
    instance_id: int
    stream: StreamSpec
    release_time_us: float
    release_index: int
    hop_index: int = 0


@dataclass
class _Transmission:
    frame: _FrameInstance
    queue_class: QueueClass
    token: int


@dataclass
class _PortState:
    hop_index: int
    route_group: RouteGroup
    idle_slope_fraction: float
    send_slope_fraction: float
    last_update_time_us: float = 0.0
    credit_a: float = 0.0
    credit_b: float = 0.0
    current_tx: _Transmission | None = None
    queue_a: deque[_FrameInstance] = field(default_factory=deque)
    queue_b: deque[_FrameInstance] = field(default_factory=deque)
    queue_be: deque[_FrameInstance] = field(default_factory=deque)
    wakeup_token: int = 0
    tx_token: int = 0

    def advance_to(self, time_us: float) -> None:
        delta = time_us - self.last_update_time_us
        if delta <= 0:
            self.last_update_time_us = time_us
            return

        if self.current_tx is None:
            self.credit_a = self._recover_credit(self.credit_a, bool(self.queue_a), delta)
            self.credit_b = self._recover_credit(self.credit_b, bool(self.queue_b), delta)
        elif self.current_tx.queue_class == QueueClass.A:
            self.credit_a -= self.send_slope_fraction * delta
            self.credit_b = self._recover_credit(self.credit_b, bool(self.queue_b), delta)
        elif self.current_tx.queue_class == QueueClass.B:
            self.credit_b -= self.send_slope_fraction * delta
            self.credit_a = self._recover_credit(self.credit_a, bool(self.queue_a), delta)
        else:
            self.credit_a = self._recover_credit(self.credit_a, bool(self.queue_a), delta)
            self.credit_b = self._recover_credit(self.credit_b, bool(self.queue_b), delta)

        self.last_update_time_us = time_us

    def enqueue(self, frame: _FrameInstance) -> None:
        if frame.stream.queue_class == QueueClass.A:
            self.queue_a.append(frame)
        elif frame.stream.queue_class == QueueClass.B:
            self.queue_b.append(frame)
        else:
            self.queue_be.append(frame)

    def invalidate_wakeup(self) -> None:
        self.wakeup_token += 1

    def select_next_queue(self) -> QueueClass | None:
        if self.queue_a and self.credit_a >= -EPSILON:
            return QueueClass.A
        if self.queue_b and self.credit_b >= -EPSILON:
            return QueueClass.B
        if self.queue_be:
            return QueueClass.BE
        return None

    def pop_next_frame(self, queue_class: QueueClass) -> _FrameInstance:
        if queue_class == QueueClass.A:
            return self.queue_a.popleft()
        if queue_class == QueueClass.B:
            return self.queue_b.popleft()
        return self.queue_be.popleft()

    def maybe_reset_positive_credit(self, queue_class: QueueClass) -> None:
        if queue_class == QueueClass.A and not self.queue_a and self.credit_a > 0:
            self.credit_a = 0.0
        if queue_class == QueueClass.B and not self.queue_b and self.credit_b > 0:
            self.credit_b = 0.0

    def next_recovery_time_us(self) -> float | None:
        candidates = []
        if self.queue_a and self.credit_a < 0:
            candidates.append(self.last_update_time_us + (-self.credit_a / self.idle_slope_fraction))
        if self.queue_b and self.credit_b < 0:
            candidates.append(self.last_update_time_us + (-self.credit_b / self.idle_slope_fraction))
        if not candidates:
            return None
        return min(candidates)

    def _recover_credit(self, credit: float, has_backlog: bool, delta: float) -> float:
        if has_backlog:
            return credit + self.idle_slope_fraction * delta
        if credit < 0:
            return min(0.0, credit + self.idle_slope_fraction * delta)
        return 0.0


@dataclass(frozen=True)
class StreamSimulation:
    stream_id: int
    queue_class: QueueClass
    observed_pure_wcd_us: float
    observed_delivery_wcd_us: float
    frame_instances: int


@dataclass(frozen=True)
class SimulationResult:
    by_stream_id: dict[int, StreamSimulation]
    simulated_until_us: float


def simulate_case(
    case: NetworkCase,
    cycles: int = 5,
    idle_slope_fraction: float = 0.5,
    send_slope_fraction: float = 0.5,
) -> SimulationResult:
    if cycles <= 0:
        raise ValueError("cycles must be positive.")

    aggregate_results: dict[int, StreamSimulation] = {}
    final_time = 0.0
    for route_group in case.route_groups:
        group_results, group_final_time = _simulate_route_group(
            route_group=route_group,
            cycles=cycles,
            idle_slope_fraction=idle_slope_fraction,
            send_slope_fraction=send_slope_fraction,
        )
        aggregate_results.update(group_results)
        final_time = max(final_time, group_final_time)

    return SimulationResult(by_stream_id=aggregate_results, simulated_until_us=final_time)


def _simulate_route_group(
    route_group: RouteGroup,
    cycles: int,
    idle_slope_fraction: float,
    send_slope_fraction: float,
) -> tuple[dict[int, StreamSimulation], float]:
    ports = [
        _PortState(
            hop_index=hop_index,
            route_group=route_group,
            idle_slope_fraction=idle_slope_fraction,
            send_slope_fraction=send_slope_fraction,
        )
        for hop_index in range(route_group.hop_count)
    ]

    event_queue: list[tuple[float, int, str, object]] = []
    event_counter = itertools.count()
    frame_counter = itertools.count()

    horizon_us = _compute_horizon_us(route_group.streams, cycles)
    for stream in route_group.streams:
        release_count = int(math.ceil(horizon_us / stream.period_us))
        for release_index in range(release_count):
            release_time_us = release_index * stream.period_us
            if release_time_us >= horizon_us - EPSILON:
                break
            frame = _FrameInstance(
                instance_id=next(frame_counter),
                stream=stream,
                release_time_us=release_time_us,
                release_index=release_index,
            )
            _push_event(event_queue, event_counter, release_time_us, "release", frame)

    observed_pure: dict[int, float] = defaultdict(float)
    observed_delivery: dict[int, float] = defaultdict(float)
    frame_counts: dict[int, int] = defaultdict(int)
    current_time = 0.0

    while event_queue:
        current_time, same_time_events = _pop_same_time_events(event_queue)
        touched_ports: set[int] = set()

        for _, _, event_type, payload in same_time_events:
            if event_type in {"release", "arrival"}:
                frame = payload
                port = ports[frame.hop_index]
                port.advance_to(current_time)
                port.enqueue(frame)
                touched_ports.add(port.hop_index)
            elif event_type == "tx_complete":
                port_index, token = payload
                port = ports[port_index]
                port.advance_to(current_time)
                if port.current_tx is None or port.current_tx.token != token:
                    continue

                transmission = port.current_tx
                port.current_tx = None
                port.maybe_reset_positive_credit(transmission.queue_class)
                touched_ports.add(port.hop_index)

                finished_frame = transmission.frame
                current_hop = finished_frame.stream.hops[finished_frame.hop_index]
                if finished_frame.hop_index + 1 < finished_frame.stream.hop_count:
                    forwarded_frame = _FrameInstance(
                        instance_id=finished_frame.instance_id,
                        stream=finished_frame.stream,
                        release_time_us=finished_frame.release_time_us,
                        release_index=finished_frame.release_index,
                        hop_index=finished_frame.hop_index + 1,
                    )
                    _push_event(
                        event_queue,
                        event_counter,
                        current_time + current_hop.propagation_delay_us,
                        "arrival",
                        forwarded_frame,
                    )
                else:
                    pure_delay = current_time - finished_frame.release_time_us
                    delivery_delay = pure_delay + current_hop.propagation_delay_us
                    stream_id = finished_frame.stream.stream_id
                    observed_pure[stream_id] = max(observed_pure[stream_id], pure_delay)
                    observed_delivery[stream_id] = max(observed_delivery[stream_id], delivery_delay)
                    frame_counts[stream_id] += 1
            elif event_type == "wakeup":
                port_index, token = payload
                port = ports[port_index]
                port.advance_to(current_time)
                if token != port.wakeup_token:
                    continue
                touched_ports.add(port.hop_index)
            else:
                raise ValueError(f"Unknown event type: {event_type}")

        for port_index in touched_ports:
            port = ports[port_index]
            port.invalidate_wakeup()
            _dispatch_or_schedule(port, current_time, event_queue, event_counter)

    results = {
        stream.stream_id: StreamSimulation(
            stream_id=stream.stream_id,
            queue_class=stream.queue_class,
            observed_pure_wcd_us=observed_pure.get(stream.stream_id, 0.0),
            observed_delivery_wcd_us=observed_delivery.get(stream.stream_id, 0.0),
            frame_instances=frame_counts.get(stream.stream_id, 0),
        )
        for stream in route_group.streams
    }
    return results, current_time


def _dispatch_or_schedule(
    port: _PortState,
    current_time: float,
    event_queue: list[tuple[float, int, str, object]],
    event_counter: itertools.count,
) -> None:
    if port.current_tx is not None:
        return

    selected_queue = port.select_next_queue()
    if selected_queue is not None:
        frame = port.pop_next_frame(selected_queue)
        tx_duration_us = frame.stream.hops[port.hop_index].transmission_time_us
        port.tx_token += 1
        token = port.tx_token
        port.current_tx = _Transmission(frame=frame, queue_class=selected_queue, token=token)
        _push_event(
            event_queue,
            event_counter,
            current_time + tx_duration_us,
            "tx_complete",
            (port.hop_index, token),
        )
        return

    wakeup_time = port.next_recovery_time_us()
    if wakeup_time is not None:
        token = port.wakeup_token
        _push_event(event_queue, event_counter, wakeup_time, "wakeup", (port.hop_index, token))


def _push_event(
    event_queue: list[tuple[float, int, str, object]],
    event_counter: itertools.count,
    time_us: float,
    event_type: str,
    payload: object,
) -> None:
    heapq.heappush(event_queue, (time_us, next(event_counter), event_type, payload))


def _pop_same_time_events(
    event_queue: list[tuple[float, int, str, object]]
) -> tuple[float, list[tuple[float, int, str, object]]]:
    first = heapq.heappop(event_queue)
    current_time = first[0]
    same_time_events = [first]
    while event_queue and abs(event_queue[0][0] - current_time) <= EPSILON:
        same_time_events.append(heapq.heappop(event_queue))
    return current_time, same_time_events


def _compute_horizon_us(streams: tuple[StreamSpec, ...], cycles: int) -> float:
    periods = [stream.period_us for stream in streams]
    rounded = [round(period) for period in periods]
    if all(abs(period - rounded_period) <= EPSILON for period, rounded_period in zip(periods, rounded)):
        hyperperiod = rounded[0]
        for period in rounded[1:]:
            hyperperiod = math.lcm(hyperperiod, period)
        return float(hyperperiod * cycles)
    return max(periods) * cycles

