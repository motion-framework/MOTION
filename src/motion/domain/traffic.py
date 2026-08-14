"""Traffic observations received from external providers."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .geography import approximate_geo_distance_meters

JAM_THRESHOLD_FREE = 3.0
JAM_THRESHOLD_SLOW = 7.0
INCIDENT_MATCH_RADIUS_M = 150.0


@dataclass(frozen=True, slots=True)
class TrafficSegment:
    description: str
    length_m: float
    speed_kmh: float
    free_kmh: float
    jam_factor: float
    confidence: float
    incidents_nearby: int = 0
    road_closure: bool = False
    lat: float = 0.0
    lon: float = 0.0
    shape_points: tuple[tuple[float, float], ...] = ()
    functional_class: int = 0

    @property
    def congestion_level(self) -> str:
        if self.jam_factor < JAM_THRESHOLD_FREE:
            return "FREE"
        if self.jam_factor < JAM_THRESHOLD_SLOW:
            return "SLOW"
        return "JAM"


@dataclass(frozen=True, slots=True)
class TrafficIncident:
    description: str
    incident_type: str
    criticality: str
    road_closed: bool
    lat: float
    lon: float


def enrich_segments_with_incidents(
    segments: list[TrafficSegment],
    incidents: list[TrafficIncident],
    match_radius_m: float = INCIDENT_MATCH_RADIUS_M,
) -> list[TrafficSegment]:
    if not incidents:
        return segments
    enriched: list[TrafficSegment] = []
    for segment in segments:
        nearby = [
            incident
            for incident in incidents
            if approximate_geo_distance_meters(
                (segment.lat, segment.lon), (incident.lat, incident.lon)
            )
            <= match_radius_m
        ]
        enriched.append(
            replace(
                segment,
                incidents_nearby=len(nearby),
                road_closure=segment.road_closure
                or any(incident.road_closed for incident in nearby),
            )
        )
    return enriched
