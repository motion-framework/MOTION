"""Map-coverage preparation for UC-01."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from motion.domain.geography import Point2D, polyline_length_meters
from motion.domain.maps import MapProfile
from motion.domain.traffic import TrafficSegment
from motion.ports.simulator import CoordinateProjector, SegmentCoverage

DEFAULT_SEGMENT_LENGTH_METERS = 100.0


class MapCoverage:
    """Clip HERE shape vertices to the active map and project them.

    Vertex-only clipping is inherited and covered by characterization tests. A
    boundary crossing is omitted when no sampled vertex falls inside the map.
    """

    def __init__(self, profile: MapProfile, projector: CoordinateProjector) -> None:
        self.profile = profile
        self._projector = projector

    @staticmethod
    def geographic_points_of(
        segment: TrafficSegment,
    ) -> tuple[tuple[float, float], ...]:
        return segment.shape_points or ((segment.lat, segment.lon),)

    def segments_touching_map(self, segments: Sequence[TrafficSegment]) -> list[TrafficSegment]:
        bbox = self.profile.bbox
        return [
            segment
            for segment in segments
            if any(
                bbox.contains(latitude, longitude)
                for latitude, longitude in self.geographic_points_of(segment)
            )
        ]

    def coverage_of(self, segment: TrafficSegment) -> SegmentCoverage:
        bbox = self.profile.bbox
        points_inside_map = [
            (latitude, longitude)
            for latitude, longitude in self.geographic_points_of(segment)
            if bbox.contains(latitude, longitude)
        ]
        return SegmentCoverage(
            segment=segment,
            points_xy=tuple(
                self._projector.to_xy(latitude, longitude)
                for latitude, longitude in points_inside_map
            ),
        )

    def coverages_of(self, segments: Sequence[TrafficSegment]) -> list[SegmentCoverage]:
        return [self.coverage_of(segment) for segment in segments]

    @staticmethod
    def resized_for_population(coverage: SegmentCoverage) -> SegmentCoverage:
        length_inside_map = (
            polyline_length_meters(coverage.points_xy) or DEFAULT_SEGMENT_LENGTH_METERS
        )
        return replace(
            coverage,
            segment=replace(coverage.segment, length_m=length_inside_map),
        )

    def device_anchor_points(self) -> tuple[Point2D, ...]:
        return tuple(
            self._projector.to_xy(latitude, longitude)
            for latitude, longitude in self.profile.device_registry.values()
        )
