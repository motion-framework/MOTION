"""Deterministic HERE road-selection rules."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise

from traffic_mirror.config.paths import ProjectPaths, validate_map_name
from traffic_mirror.config.runtime_state import ActiveMapState
from traffic_mirror.domain.geography import BoundingBox
from traffic_mirror.domain.traffic import TrafficSegment

DEVICES_PER_ROAD = 4
GEO_FILTER_RADIUS_METERS = 500.0
MINIMUM_REALTIME_CONFIDENCE = 0.71
MOTORWAY_FUNCTIONAL_CLASS_CEILING = 2


class RoadSelectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RoadCandidate:
    name: str
    segments: tuple[TrafficSegment, ...]

    @property
    def average_speed_kmh(self) -> float:
        return sum(segment.speed_kmh for segment in self.segments) / len(self.segments)

    @property
    def average_jam_factor(self) -> float:
        return sum(segment.jam_factor for segment in self.segments) / len(self.segments)


def group_by_road(segments: Sequence[TrafficSegment]) -> list[RoadCandidate]:
    grouped: dict[str, list[TrafficSegment]] = defaultdict(list)
    for segment in segments:
        grouped[segment.description].append(segment)
    return [
        RoadCandidate(name, tuple(road_segments))
        for name, road_segments in sorted(
            grouped.items(), key=lambda item: len(item[1]), reverse=True
        )
    ]


def representative_segment(
    road_segments: Sequence[TrafficSegment], center: tuple[float, float]
) -> TrafficSegment:
    if not road_segments:
        raise RoadSelectionError("Cannot select from an empty road.")
    center_lat, center_lon = center
    return min(
        road_segments,
        key=lambda segment: (segment.lat - center_lat) ** 2 + (segment.lon - center_lon) ** 2,
    )


def segments_near_center(
    segments: Sequence[TrafficSegment],
    center: tuple[float, float],
    radius_meters: float = GEO_FILTER_RADIUS_METERS,
) -> list[TrafficSegment]:
    center_lat, center_lon = center
    metres_per_degree_lat = 111_320.0
    metres_per_degree_lon = metres_per_degree_lat * math.cos(math.radians(center_lat))

    def nearest_vertex_distance(segment: TrafficSegment) -> float:
        polyline = list(segment.shape_points) or [(segment.lat, segment.lon)]
        return min(
            math.hypot(
                (point_lat - center_lat) * metres_per_degree_lat,
                (point_lon - center_lon) * metres_per_degree_lon,
            )
            for point_lat, point_lon in polyline
        )

    return [segment for segment in segments if nearest_vertex_distance(segment) <= radius_meters]


def select_main_road_segment(
    near_segments: Sequence[TrafficSegment], center: tuple[float, float]
) -> TrafficSegment:
    """Preserve the legacy geo-mode ranking (coverage first, then distance)."""

    if not near_segments:
        raise RoadSelectionError("No HERE segment is near the requested point.")
    center_lat, center_lon = center

    def nearest_shape_distance_degrees(segment: TrafficSegment) -> float:
        polyline = list(segment.shape_points) or [(segment.lat, segment.lon)]
        return min(
            math.hypot(point_lat - center_lat, point_lon - center_lon)
            for point_lat, point_lon in polyline
        )

    def is_motorway(segment: TrafficSegment) -> bool:
        return 0 < segment.functional_class <= MOTORWAY_FUNCTIONAL_CLASS_CEILING

    urban = [segment for segment in near_segments if not is_motorway(segment)]
    if not urban:
        urban = list(near_segments)
    named = [
        segment for segment in urban if segment.description.strip().lower() not in {"", "unknown"}
    ] or urban
    realtime = [segment for segment in named if segment.confidence >= MINIMUM_REALTIME_CONFIDENCE]
    candidates = realtime or named
    by_name: dict[str, list[TrafficSegment]] = defaultdict(list)
    for segment in candidates:
        by_name[segment.description].append(segment)

    def road_sort_key(item: tuple[str, list[TrafficSegment]]) -> tuple[float, ...]:
        _, road_segments = item
        count = len(road_segments)
        average_confidence = sum(segment.confidence for segment in road_segments) / count
        nearest_distance = min(nearest_shape_distance_degrees(segment) for segment in road_segments)
        return float(count), average_confidence, -nearest_distance

    _, best_segments = max(by_name.items(), key=road_sort_key)
    return min(best_segments, key=nearest_shape_distance_degrees)


def choose_road_interactively(
    roads: Sequence[RoadCandidate],
    *,
    input_reader: Callable[[str], str] = input,
) -> RoadCandidate:
    if not roads:
        raise RoadSelectionError("HERE returned no named road candidates.")
    raw = input_reader(f"Road number to mirror (1..{len(roads)}, or 'q' to quit): ").strip()
    if raw.lower() == "q":
        raise KeyboardInterrupt
    try:
        chosen_index = int(raw)
    except ValueError as error:
        raise RoadSelectionError(f"{raw!r} is not a road number.") from error
    # Intentional correction: the legacy list indexing accepted 0 and negative
    # numbers, selecting from the end despite the displayed 1..N contract.
    if not 1 <= chosen_index <= len(roads):
        raise RoadSelectionError(f"{raw!r} is not one of 1..{len(roads)}.")
    return roads[chosen_index - 1]


def cut_road_around_midpoint(
    points: Sequence[tuple[float, float]], half_length_metres: float
) -> list[tuple[float, float]]:
    if len(points) < 2:
        return list(points)
    reference_latitude = points[0][0]

    def distance(first: tuple[float, float], second: tuple[float, float]) -> float:
        metres_per_degree_lon = 111_320.0 * math.cos(math.radians(reference_latitude))
        return math.hypot(
            (first[0] - second[0]) * 111_320.0,
            (first[1] - second[1]) * metres_per_degree_lon,
        )

    cumulative = [0.0]
    for first, second in pairwise(points):
        cumulative.append(cumulative[-1] + distance(first, second))
    total = cumulative[-1]
    keep_start = max(0.0, total / 2.0 - half_length_metres)
    keep_end = min(total, total / 2.0 + half_length_metres)
    if keep_start <= 0.0 and keep_end >= total:
        return list(points)

    def point_at(target: float) -> tuple[float, float]:
        for index, (start, end) in enumerate(pairwise(cumulative)):
            if start <= target <= end:
                span = end - start
                fraction = 0.0 if span == 0 else (target - start) / span
                return (
                    points[index][0] + (points[index + 1][0] - points[index][0]) * fraction,
                    points[index][1] + (points[index + 1][1] - points[index][1]) * fraction,
                )
        return points[-1]

    cut = [point_at(keep_start)]
    cut.extend(
        point for index, point in enumerate(points) if keep_start < cumulative[index] < keep_end
    )
    cut.append(point_at(keep_end))
    return cut


def device_positions(
    segment: TrafficSegment,
    device_count: int,
    map_bbox: BoundingBox,
) -> list[tuple[float, float]]:
    points = list(segment.shape_points) or [(segment.lat, segment.lon)]
    inside = [point for point in points if map_bbox.contains(point[0], point[1])]
    selected = sorted(inside or points)
    if len(selected) == 1 or device_count == 1:
        return [selected[0]] * device_count
    step = (len(selected) - 1) / (device_count - 1)
    return [selected[round(index * step)] for index in range(device_count)]


def build_map_state_for_road(
    *,
    segment: TrafficSegment,
    radius_meters: float,
    map_name: str,
    project_paths: ProjectPaths,
    device_count: int = DEVICES_PER_ROAD,
) -> tuple[ActiveMapState, TrafficSegment]:
    validate_map_name(map_name)
    cut_points = cut_road_around_midpoint(segment.shape_points, radius_meters)
    if not cut_points:
        raise RoadSelectionError(
            "The selected HERE segment has no geometry; it cannot anchor a map."
        )
    selected = replace(segment, shape_points=tuple(cut_points))
    anchor_lat, anchor_lon = cut_points[len(cut_points) // 2]
    bbox = BoundingBox.from_center(anchor_lat, anchor_lon, radius_meters)
    registry = {
        f"{map_name.upper()}_{index + 1:03d}": position
        for index, position in enumerate(device_positions(selected, device_count, bbox))
    }
    state = ActiveMapState.for_new_map(
        name=map_name,
        bbox=bbox,
        project_paths=project_paths,
        device_registry=registry,
        geo_filter=True,
        anchor_functional_class=selected.functional_class,
        source="here-road-selection",
    )
    return state, selected
