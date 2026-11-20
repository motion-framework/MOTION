"""UC-01 tick reporting, independent of CARLA."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Protocol, TextIO

from motion.domain.devices import DeviceReading
from motion.domain.traffic import TrafficSegment


@dataclass(frozen=True, slots=True)
class TickResult:
    timestamp: float
    readings: tuple[DeviceReading, ...]
    segments: tuple[TrafficSegment, ...]
    active_vehicle_count: int
    target_vehicle_count: int
    commanded_vehicle_count: int
    repinned_vehicle_count: int
    removed_vehicle_count: int


class TickReporter(Protocol):
    def report(self, result: TickResult) -> None: ...


class NullTickReporter:
    def report(self, result: TickResult) -> None:
        del result


class ConsoleDashboardReporter:
    """Preserve the compact UC-01 dashboard emitted after every mirror tick.

    Both input sections carry their origin: ``traffic_source_label`` names the
    flow source (live HERE or the synthetic HERE-compatible provider) and
    ``device_source_label`` names the field-device source, so synthetic
    readings are never mistaken for observations when they appear next to
    live HERE data.
    """

    def __init__(
        self,
        map_name: str,
        *,
        device_registry: dict[str, tuple[float, float]] | None = None,
        traffic_source_label: str = "HERE",
        device_source_label: str = "",
        stream: TextIO | None = None,
    ) -> None:
        self._map_name = map_name
        self._device_registry = dict(device_registry or {})
        self._traffic_source_label = traffic_source_label
        self._device_source_label = device_source_label
        self._stream = stream if stream is not None else sys.stdout

    def report(self, result: TickResult) -> None:
        write = self._stream.write
        write("\n" + "=" * 60 + "\n")
        write(f"MOTION UC-01 | {self._map_name.upper()} DIGITAL TWIN\n")
        write(
            f"Timestamp      : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(result.timestamp))}\n"
        )
        write(
            f"Active vehicles: {result.active_vehicle_count}  |  "
            f"Population target: {result.target_vehicle_count}\n"
        )
        device_heading = (
            f"FIELD DEVICES ({self._device_source_label})"
            if self._device_source_label
            else "FIELD DEVICES"
        )
        write("-" * 60 + f"\n{device_heading}:\n")
        for reading in result.readings:
            coordinates = self._device_registry.get(reading.device_id)
            coordinate_text = (
                f"({coordinates[0]:.4f}, {coordinates[1]:.4f})" if coordinates else "UNREGISTERED"
            )
            write(
                f"  {reading.device_id}  {coordinate_text}  "
                f"count={reading.count:>3}  speed={reading.speed_kmh:>5.1f} km/h\n"
            )
        write(f"\n{self._traffic_source_label} FLOW ENRICHMENT:\n")
        if not result.segments:
            write(f"  No {self._traffic_source_label} segments received.\n")
        else:
            average_speed = sum(segment.speed_kmh for segment in result.segments) / len(
                result.segments
            )
            average_jam = sum(segment.jam_factor for segment in result.segments) / len(
                result.segments
            )
            write(f"  Segments  : {len(result.segments)}\n")
            write(f"  Avg speed : {average_speed:.1f} km/h\n")
            write(f"  Avg jam   : {average_jam:.2f} / 10.0\n")
            for segment in result.segments:
                write(
                    f"  {segment.description:<35} "
                    f"speed={segment.speed_kmh:>5.1f} km/h  "
                    f"jam={segment.jam_factor:.1f}  "
                    f"incidents={segment.incidents_nearby}  "
                    f"closed={segment.road_closure}  "
                    f"[{segment.congestion_level}]\n"
                )
        write("=" * 60 + "\n\n")
