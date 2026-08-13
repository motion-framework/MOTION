"""Geographic value objects and deterministic distance calculations.

The formulae intentionally preserve the numerical conventions of the original
scripts.  They are local approximations, not geodesic calculations.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

METRES_PER_DEGREE_LATITUDE = 111_320.0
DEFAULT_CENTER_RADIUS_METERS = 1_500.0

Point2D = tuple[float, float]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    south_west_lat: float
    south_west_lon: float
    north_east_lat: float
    north_east_lon: float

    def __post_init__(self) -> None:
        values = (
            self.south_west_lat,
            self.south_west_lon,
            self.north_east_lat,
            self.north_east_lon,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Bounding-box coordinates must be finite")
        if not -90.0 <= self.south_west_lat < self.north_east_lat <= 90.0:
            raise ValueError("Bounding-box latitude limits must be ordered within [-90, 90]")
        if not -180.0 <= self.south_west_lon < self.north_east_lon <= 180.0:
            raise ValueError("Bounding-box longitude limits must be ordered within [-180, 180]")

    @property
    def center_lat(self) -> float:
        return (self.south_west_lat + self.north_east_lat) / 2

    @property
    def center_lon(self) -> float:
        return (self.south_west_lon + self.north_east_lon) / 2

    def contains(self, latitude_deg: float, longitude_deg: float) -> bool:
        return (
            self.south_west_lat <= latitude_deg <= self.north_east_lat
            and self.south_west_lon <= longitude_deg <= self.north_east_lon
        )

    def to_overpass_bbox(self) -> str:
        # The Overpass /api/map endpoint expects west,south,east,north.
        return (
            f"{self.south_west_lon},{self.south_west_lat},"
            f"{self.north_east_lon},{self.north_east_lat}"
        )

    def to_here_bbox(self) -> str:
        return f"bbox:{self.to_overpass_bbox()}"

    @classmethod
    def from_center(
        cls,
        latitude: float,
        longitude: float,
        radius_meters: float = DEFAULT_CENTER_RADIUS_METERS,
    ) -> BoundingBox:
        if radius_meters <= 0 or not math.isfinite(radius_meters):
            raise ValueError("radius_meters must be finite and positive")
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError("Center coordinates must be finite")
        if not -90.0 < latitude < 90.0 or not -180.0 <= longitude <= 180.0:
            raise ValueError("Center coordinates are outside supported WGS84 limits")
        metres_per_degree_longitude = METRES_PER_DEGREE_LATITUDE * math.cos(math.radians(latitude))
        degrees_of_latitude = radius_meters / METRES_PER_DEGREE_LATITUDE
        degrees_of_longitude = radius_meters / metres_per_degree_longitude
        return cls(
            south_west_lat=latitude - degrees_of_latitude,
            south_west_lon=longitude - degrees_of_longitude,
            north_east_lat=latitude + degrees_of_latitude,
            north_east_lon=longitude + degrees_of_longitude,
        )


def planar_distance_meters(
    first_x: float, first_y: float, second_x: float, second_y: float
) -> float:
    return math.hypot(first_x - second_x, first_y - second_y)


def distance_point_to_line_segment(
    point_x: float,
    point_y: float,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> float:
    edge_x = end_x - start_x
    edge_y = end_y - start_y
    edge_length_squared = edge_x * edge_x + edge_y * edge_y
    if edge_length_squared == 0.0:
        return planar_distance_meters(point_x, point_y, start_x, start_y)
    projection_ratio = (
        (point_x - start_x) * edge_x + (point_y - start_y) * edge_y
    ) / edge_length_squared
    ratio_inside_segment = max(0.0, min(1.0, projection_ratio))
    closest_x = start_x + ratio_inside_segment * edge_x
    closest_y = start_y + ratio_inside_segment * edge_y
    return planar_distance_meters(point_x, point_y, closest_x, closest_y)


def distance_point_to_polyline(
    point_x: float, point_y: float, polyline_points: Sequence[Point2D]
) -> float:
    if not polyline_points:
        return float("inf")
    if len(polyline_points) == 1:
        only_x, only_y = polyline_points[0]
        return planar_distance_meters(point_x, point_y, only_x, only_y)
    return min(
        distance_point_to_line_segment(point_x, point_y, start_x, start_y, end_x, end_y)
        for (start_x, start_y), (end_x, end_y) in pairwise(polyline_points)
    )


def polyline_length_meters(polyline_points: Sequence[Point2D]) -> float:
    return sum(
        planar_distance_meters(start_x, start_y, end_x, end_y)
        for (start_x, start_y), (end_x, end_y) in pairwise(polyline_points)
    )


def approximate_geo_distance_meters(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    first_lat, first_lon = first
    second_lat, second_lon = second
    mean_latitude_rad = math.radians((first_lat + second_lat) / 2.0)
    north_south_m = (second_lat - first_lat) * METRES_PER_DEGREE_LATITUDE
    east_west_m = (
        (second_lon - first_lon) * METRES_PER_DEGREE_LATITUDE * math.cos(mean_latitude_rad)
    )
    return math.hypot(east_west_m, north_south_m)


def cumulative_distances_meters(
    points: Sequence[tuple[float, float]],
) -> list[float]:
    distances = [0.0]
    for previous_point, next_point in pairwise(points):
        distances.append(
            distances[-1] + approximate_geo_distance_meters(previous_point, next_point)
        )
    return distances


def slice_polyline_nearest_vertices(
    points: Sequence[tuple[float, float]],
    cumulative: Sequence[float],
    start_m: float,
    end_m: float,
) -> tuple[tuple[float, float], ...]:
    """Preserve HERE subsegment slicing from the legacy parser."""

    inside = [
        point
        for point, travelled in zip(points, cumulative, strict=True)
        if start_m <= travelled <= end_m
    ]
    if len(inside) >= 2:
        return tuple(inside)
    middle_m = (start_m + end_m) / 2.0
    nearest = min(range(len(points)), key=lambda index: abs(cumulative[index] - middle_m))
    return tuple(points[max(0, nearest - 1) : nearest + 2])
