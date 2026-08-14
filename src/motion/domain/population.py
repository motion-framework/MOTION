"""Vehicle-density policy derived from HERE jam factors."""

from __future__ import annotations

from .traffic import TrafficSegment

JAM_FACTOR_MAX = 10.0
JAM_DENSITY_VEH_PER_KM = 120.0
MAX_VEHICLES_PER_SEGMENT = 40


def segment_target_vehicle_count(
    segment: TrafficSegment,
    max_vehicles: int = MAX_VEHICLES_PER_SEGMENT,
) -> int:
    if segment.road_closure:
        congestion = 1.0
    else:
        congestion = min(max(segment.jam_factor / JAM_FACTOR_MAX, 0.0), 1.0)
    density_vehicles_per_km = congestion * JAM_DENSITY_VEH_PER_KM
    raw_count = density_vehicles_per_km * (segment.length_m / 1_000.0)
    return min(round(raw_count), max_vehicles)


def derive_population_targets(
    segments: list[TrafficSegment], max_total: int
) -> list[tuple[TrafficSegment, int]]:
    """Scale segment targets exactly as the legacy implementation did.

    Independent rounding can make the resulting sum differ from ``max_total``;
    characterization tests retain that inherited numerical behavior.
    """

    targets = [(segment, segment_target_vehicle_count(segment)) for segment in segments]
    total = sum(count for _, count in targets)
    if total <= max_total or total == 0:
        return targets
    scale = max_total / total
    return [(segment, round(count * scale)) for segment, count in targets]
