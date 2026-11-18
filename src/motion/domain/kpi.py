"""Pure KPI math shared by UC-02 (delta report) and UC-03 (heatmap/corridor).

The baseline snapshot is computed directly from real HERE segments (the UC-02
precondition is "UC-01 active / real baseline available"; no simulation is
needed to know what real traffic looks like today). The scenario snapshot is
computed from what the simulator actually measured after running UC-01's own
mirroring loop against the modified map. See docs/scenario-kpis.md for the
full methodology and its documented approximations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .mirroring import MAXIMUM_VEHICLE_COUNT
from .population import derive_population_targets
from .traffic import TrafficSegment

DEFAULT_GRAMS_CO2_PER_VEHICLE_KM = 120.0
"""Rough average-passenger-car CO2 approximation in grams per vehicle-km.

This is a deliberate simplification, not a validated emissions model: MOTION
has no fleet-composition or per-vehicle-type data. It is overridable by the
caller (CLI: ``--grams-co2-per-km``) and is documented as approximate in
docs/scenario-kpis.md.
"""


def travel_time_seconds(length_m: float, speed_kmh: float) -> float:
    """Time to cross ``length_m`` at a constant ``speed_kmh``.

    Returns 0.0 for a non-positive length. A non-positive speed makes the
    distance uncrossable at that rate and is reported as ``inf`` rather than
    silently clamped, matching this repository's no-silent-clipping
    convention (see docs/data-contracts.md).
    """

    if length_m <= 0.0:
        return 0.0
    if speed_kmh <= 0.0:
        return float("inf")
    return length_m / (speed_kmh / 3.6)


def density_vehicles_per_km(vehicle_count: int, length_m: float) -> float:
    """Vehicles per kilometre over ``length_m``; 0.0 when there is no length."""

    if length_m <= 0.0:
        return 0.0
    return vehicle_count / (length_m / 1_000.0)


def co2_grams(
    vehicle_count: int,
    distance_km: float,
    grams_per_vehicle_km: float = DEFAULT_GRAMS_CO2_PER_VEHICLE_KM,
) -> float:
    """Total estimated CO2 grams for ``vehicle_count`` vehicles each travelling
    ``distance_km``, using a flat per-vehicle-km emission approximation."""

    return vehicle_count * distance_km * grams_per_vehicle_km


@dataclass(frozen=True, slots=True)
class KpiSnapshot:
    """One side (baseline or scenario) of a before/after KPI comparison."""

    corridor_travel_time_seconds: float
    average_density_vehicles_per_km: float
    total_co2_grams: float
    vehicle_count: int
    distance_km: float


@dataclass(frozen=True, slots=True)
class KpiDelta:
    """``scenario - baseline`` for each KPI; negative means an improvement."""

    travel_time_seconds: float
    density_vehicles_per_km: float
    co2_grams: float

    @classmethod
    def between(cls, baseline: KpiSnapshot, scenario: KpiSnapshot) -> KpiDelta:
        return cls(
            travel_time_seconds=(
                scenario.corridor_travel_time_seconds - baseline.corridor_travel_time_seconds
            ),
            density_vehicles_per_km=(
                scenario.average_density_vehicles_per_km - baseline.average_density_vehicles_per_km
            ),
            co2_grams=scenario.total_co2_grams - baseline.total_co2_grams,
        )


def snapshot_from_segments(
    segments: Sequence[TrafficSegment],
    *,
    grams_per_vehicle_km: float = DEFAULT_GRAMS_CO2_PER_VEHICLE_KM,
    max_total_vehicles: int = MAXIMUM_VEHICLE_COUNT,
) -> KpiSnapshot:
    """The baseline snapshot, computed directly from real HERE segments.

    Both sides of the comparison must describe the same quantity over the same
    corridor, so:

    - ``corridor_travel_time_seconds`` is the time to traverse the **whole**
      corridor -- the sum of each segment's own crossing time (see
      ``travel_time_seconds``) -- matching ``snapshot_from_measured``, which
      crosses the same total ``distance_km`` at the measured speed. A mean of
      per-segment times would describe one average segment, not the corridor,
      and could not be differenced against the measured value.
    - Vehicle counts reuse ``domain.population.derive_population_targets``
      with the same ``max_total_vehicles`` budget UC-01's mirroring loop
      applies, so the baseline count is what UC-01 would actually mirror for
      this traffic. Summing uncapped per-segment targets instead would make
      the baseline exceed the simulator's own population ceiling, and every
      density/CO2 delta would then measure that ceiling rather than the
      scenario.
    """

    if not segments:
        return KpiSnapshot(0.0, 0.0, 0.0, 0, 0.0)

    total_length_m = sum(segment.length_m for segment in segments)
    total_vehicle_count = sum(
        count for _segment, count in derive_population_targets(list(segments), max_total_vehicles)
    )
    corridor_travel_time = sum(
        travel_time_seconds(segment.length_m, segment.speed_kmh) for segment in segments
    )
    distance_km = total_length_m / 1_000.0

    return KpiSnapshot(
        corridor_travel_time_seconds=corridor_travel_time,
        average_density_vehicles_per_km=density_vehicles_per_km(
            total_vehicle_count, total_length_m
        ),
        total_co2_grams=co2_grams(total_vehicle_count, distance_km, grams_per_vehicle_km),
        vehicle_count=total_vehicle_count,
        distance_km=distance_km,
    )


def snapshot_from_measured(
    *,
    vehicle_count: int,
    average_speed_kmh: float | None,
    distance_km: float,
    grams_per_vehicle_km: float = DEFAULT_GRAMS_CO2_PER_VEHICLE_KM,
) -> KpiSnapshot:
    """The scenario snapshot, from what the simulator actually measured.

    ``average_speed_kmh`` is ``TrafficSimulator.average_speed_kmh()`` after
    running the modified-map mirroring loop -- a real measurement, not a
    policy echo. ``None`` (no owned vehicles observed) is reported as an
    all-zero snapshot rather than an infinite travel time, since there is
    nothing to measure.
    """

    if average_speed_kmh is None or vehicle_count <= 0:
        return KpiSnapshot(0.0, 0.0, 0.0, 0, distance_km)

    distance_m = distance_km * 1_000.0
    return KpiSnapshot(
        corridor_travel_time_seconds=travel_time_seconds(distance_m, average_speed_kmh),
        average_density_vehicles_per_km=density_vehicles_per_km(vehicle_count, distance_m),
        total_co2_grams=co2_grams(vehicle_count, distance_km, grams_per_vehicle_km),
        vehicle_count=vehicle_count,
        distance_km=distance_km,
    )
