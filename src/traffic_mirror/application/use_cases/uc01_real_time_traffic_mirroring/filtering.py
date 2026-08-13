"""Characterized HERE-segment selection for UC-01."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from traffic_mirror.domain.geography import Point2D, planar_distance_meters
from traffic_mirror.domain.traffic import TrafficSegment

from .coverage import MapCoverage

GEO_SEGMENT_FILTER_RADIUS_METERS = 150.0
FUNCTIONAL_CLASS_TOLERANCE = 1


@dataclass(frozen=True, slots=True)
class SegmentFilter:
    road_filter: str = ""
    geo_filter: bool = False
    anchor_functional_class: int | None = None

    def apply(
        self,
        segments: Sequence[TrafficSegment],
        *,
        coverage: MapCoverage,
        device_points: Sequence[Point2D],
    ) -> list[TrafficSegment]:
        segment_list = list(segments)
        if self.geo_filter:
            return self._near_devices(segment_list, coverage=coverage, device_points=device_points)
        if not self.road_filter:
            return segment_list
        matching = [
            segment
            for segment in segment_list
            if self.road_filter.lower() in segment.description.lower()
        ]
        # Preserve the legacy non-empty fallback.
        return matching or segment_list

    def _near_devices(
        self,
        segments: list[TrafficSegment],
        *,
        coverage: MapCoverage,
        device_points: Sequence[Point2D],
    ) -> list[TrafficSegment]:
        if not device_points:
            return segments

        geometrically_near: list[TrafficSegment] = []
        for segment_coverage in coverage.coverages_of(segments):
            if not segment_coverage.points_xy:
                continue
            nearest_to_device = min(
                min(
                    planar_distance_meters(point_x, point_y, device_x, device_y)
                    for device_x, device_y in device_points
                )
                for point_x, point_y in segment_coverage.points_xy
            )
            if nearest_to_device <= GEO_SEGMENT_FILTER_RADIUS_METERS:
                geometrically_near.append(segment_coverage.segment)

        if not geometrically_near:
            return segments
        if self.anchor_functional_class is None:
            return geometrically_near

        kept = [
            segment
            for segment in geometrically_near
            if segment.functional_class == 0
            or abs(segment.functional_class - self.anchor_functional_class)
            <= FUNCTIONAL_CLASS_TOLERANCE
        ]
        return kept or geometrically_near
