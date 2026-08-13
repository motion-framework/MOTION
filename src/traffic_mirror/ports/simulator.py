"""Simulator-neutral contracts used by UC-01.

The application layer exchanges geographic coverage and domain driving
commands with a simulator adapter.  No type in this module imports CARLA.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from traffic_mirror.domain.geography import Point2D, distance_point_to_polyline
from traffic_mirror.domain.mirroring import DrivingCommand
from traffic_mirror.domain.traffic import TrafficSegment


class CoordinateProjector(Protocol):
    """Project WGS84 coordinates into the simulator's planar coordinate space."""

    def to_xy(self, latitude_deg: float, longitude_deg: float) -> Point2D: ...


@dataclass(frozen=True, slots=True)
class SegmentCoverage:
    """A traffic segment together with the part represented in the simulator."""

    segment: TrafficSegment
    points_xy: tuple[Point2D, ...]

    def distance_from(self, point_xy: Point2D) -> float:
        return distance_point_to_polyline(point_xy[0], point_xy[1], self.points_xy)


@dataclass(frozen=True, slots=True)
class PopulationTarget:
    coverage: SegmentCoverage
    target_count: int


@dataclass(frozen=True, slots=True)
class SegmentCommand:
    coverage: SegmentCoverage
    command: DrivingCommand


class TrafficSimulator(Protocol):
    """Operations UC-01 requires from a traffic simulator.

    Implementations own the actors they create.  Population management,
    sanitization and cleanup must never destroy actors outside that ownership
    set.
    """

    def owned_vehicle_count(self) -> int: ...

    def synchronize_population(self, targets: Sequence[PopulationTarget]) -> int: ...

    def synchronize_uniform_population(
        self, target_count: int, coverage_anchor_points: Sequence[Point2D]
    ) -> int: ...

    def apply_segment_commands(
        self,
        commands: Sequence[SegmentCommand],
        fallback_command: DrivingCommand,
    ) -> int: ...

    def repin_to_road(self, coverages: Sequence[SegmentCoverage]) -> int: ...

    def set_mirrored_coverage(self, coverages: Sequence[SegmentCoverage]) -> None: ...

    def sanitize_tick(self) -> int: ...

    def sanitize_watchdog(self) -> int: ...

    def focus_view(self, anchor_points: Sequence[Point2D]) -> None: ...

    def close(self) -> None: ...
