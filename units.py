"""Time and link-rate helpers for TSN calculations."""

from __future__ import annotations

TIME_UNIT_TO_MICROSECONDS = {
    "SECOND": 1_000_000.0,
    "MILLI_SECOND": 1_000.0,
    "MICRO_SECOND": 1.0,
    "NANO_SECOND": 0.001,
}


def to_microseconds(value: float | int, unit: str | None) -> float:
    normalized_unit = (unit or "MICRO_SECOND").strip().upper()
    try:
        factor = TIME_UNIT_TO_MICROSECONDS[normalized_unit]
    except KeyError as exc:
        raise ValueError(f"Unsupported delay unit: {unit}") from exc
    return float(value) * factor


def transmission_time_us(size_bytes: int, bandwidth_mbps: float) -> float:
    if bandwidth_mbps <= 0:
        raise ValueError(f"Bandwidth must be positive, got {bandwidth_mbps}.")
    return (float(size_bytes) * 8.0) / float(bandwidth_mbps)

