"""Transform HERE-specific response DTOs into domain traffic models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from traffic_mirror.domain.geography import (
    cumulative_distances_meters,
    slice_polyline_nearest_vertices,
)
from traffic_mirror.domain.traffic import TrafficIncident, TrafficSegment

TRAVERSABILITY_CLOSED = "closed"


class HerePayloadError(ValueError):
    pass


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HerePayloadError(f"{context} must be a JSON object")
    return value


def parse_shape(
    shape: Mapping[str, Any], fallback_coords: tuple[float, float]
) -> tuple[float, float, tuple[tuple[float, float], ...], int]:
    raw_links = shape.get("links", [])
    if not isinstance(raw_links, list):
        raise HerePayloadError("location.shape.links must be a list")
    points: list[tuple[float, float]] = []
    functional_class = 0
    for raw_link in raw_links:
        link = _mapping(raw_link, "location.shape link")
        if functional_class == 0 and "functionalClass" in link:
            try:
                functional_class = int(link["functionalClass"])
            except (TypeError, ValueError) as error:
                raise HerePayloadError("functionalClass must be an integer") from error
        raw_points = link.get("points", [])
        if not isinstance(raw_points, list):
            raise HerePayloadError("location.shape link points must be a list")
        for raw_point in raw_points:
            point = _mapping(raw_point, "location.shape point")
            try:
                points.append((float(point["lat"]), float(point["lng"])))
            except (KeyError, TypeError, ValueError) as error:
                raise HerePayloadError("shape points require numeric lat and lng") from error

    if not points:
        return (*fallback_coords, (), functional_class)
    average_lat = sum(point[0] for point in points) / len(points)
    average_lon = sum(point[1] for point in points) / len(points)
    return average_lat, average_lon, tuple(points), functional_class


class TrafficParser:
    def __init__(self, fallback_coords: tuple[float, float]) -> None:
        self._fallback_coords = fallback_coords

    def parse(self, raw: Mapping[str, Any]) -> list[TrafficSegment]:
        raw_results = raw.get("results", [])
        if not isinstance(raw_results, list):
            raise HerePayloadError("HERE flow results must be a list")
        segments: list[TrafficSegment] = []
        for raw_result in raw_results:
            result = _mapping(raw_result, "HERE flow result")
            flow = _mapping(result.get("currentFlow", {}), "currentFlow")
            location = _mapping(result.get("location", {}), "location")

            free_ms = flow.get("freeFlow")
            speed_ms = flow.get("speed")
            if speed_ms is None:
                speed_ms = free_ms
            if free_ms is None:
                free_ms = speed_ms
            if speed_ms is None or free_ms is None:
                continue
            try:
                speed_value = float(speed_ms)
                free_value = float(free_ms)
                lat, lon, shape_points, functional_class = parse_shape(
                    _mapping(location.get("shape", {}), "location.shape"),
                    self._fallback_coords,
                )
                base_segment = TrafficSegment(
                    description=str(location.get("description", "unknown")),
                    length_m=float(location.get("length", 0.0)),
                    speed_kmh=round(speed_value * 3.6, 1),
                    free_kmh=round(free_value * 3.6, 1),
                    jam_factor=float(flow.get("jamFactor", 0.0)),
                    confidence=float(flow.get("confidence", 1.0)),
                    road_closure=str(flow.get("traversability", "open")).lower()
                    == TRAVERSABILITY_CLOSED,
                    lat=lat,
                    lon=lon,
                    shape_points=shape_points,
                    functional_class=functional_class,
                )
            except (TypeError, ValueError) as error:
                raise HerePayloadError("HERE flow contains a non-numeric field") from error
            segments.extend(self._expand_subsegments(base_segment, flow))
        return segments

    @staticmethod
    def _expand_subsegments(base: TrafficSegment, flow: Mapping[str, Any]) -> list[TrafficSegment]:
        raw_subsegments = flow.get("subSegments", [])
        points = list(base.shape_points)
        if not raw_subsegments or len(points) < 2:
            return [base]
        if not isinstance(raw_subsegments, list):
            raise HerePayloadError("currentFlow.subSegments must be a list")

        cumulative = cumulative_distances_meters(points)
        pieces: list[TrafficSegment] = []
        start_m = 0.0
        for raw_subsegment in raw_subsegments:
            raw = _mapping(raw_subsegment, "currentFlow subsegment")
            try:
                piece_length_m = float(raw.get("length", 0.0))
            except (TypeError, ValueError) as error:
                raise HerePayloadError("subsegment length must be numeric") from error
            if piece_length_m <= 0.0:
                continue
            end_m = min(start_m + piece_length_m, cumulative[-1])
            piece_points = slice_polyline_nearest_vertices(points, cumulative, start_m, end_m)
            if not piece_points:
                continue
            try:
                piece_speed_ms = float(raw.get("speed", base.speed_kmh / 3.6))
                piece_free_ms = float(raw.get("freeFlow", base.free_kmh / 3.6))
                pieces.append(
                    replace(
                        base,
                        length_m=end_m - start_m,
                        speed_kmh=round(piece_speed_ms * 3.6, 1),
                        free_kmh=round(piece_free_ms * 3.6, 1),
                        jam_factor=float(raw.get("jamFactor", base.jam_factor)),
                        confidence=float(raw.get("confidence", base.confidence)),
                        lat=sum(point[0] for point in piece_points) / len(piece_points),
                        lon=sum(point[1] for point in piece_points) / len(piece_points),
                        shape_points=piece_points,
                    )
                )
            except (TypeError, ValueError) as error:
                raise HerePayloadError("subsegment contains a non-numeric field") from error
            start_m = end_m
        return pieces or [base]


class IncidentParser:
    def __init__(self, fallback_coords: tuple[float, float]) -> None:
        self._fallback_coords = fallback_coords

    def parse(self, raw: Mapping[str, Any]) -> list[TrafficIncident]:
        raw_results = raw.get("results", [])
        if not isinstance(raw_results, list):
            raise HerePayloadError("HERE incident results must be a list")
        incidents: list[TrafficIncident] = []
        for raw_result in raw_results:
            result = _mapping(raw_result, "HERE incident result")
            details = _mapping(result.get("incidentDetails", {}), "incidentDetails")
            location = _mapping(result.get("location", {}), "location")
            lat, lon, _points, _functional_class = parse_shape(
                _mapping(location.get("shape", {}), "location.shape"),
                self._fallback_coords,
            )
            raw_description = details.get("description", {})
            if isinstance(raw_description, Mapping):
                description = raw_description.get("value", details.get("type", "unknown"))
            else:
                description = raw_description or details.get("type", "unknown")
            incidents.append(
                TrafficIncident(
                    description=str(description),
                    incident_type=str(details.get("type", "unknown")),
                    criticality=str(details.get("criticality", "unknown")),
                    road_closed=bool(details.get("roadClosed", False)),
                    lat=lat,
                    lon=lon,
                )
            )
        return incidents
