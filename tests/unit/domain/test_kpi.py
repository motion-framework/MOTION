from __future__ import annotations

import pytest

from motion.domain.kpi import (
    DEFAULT_GRAMS_CO2_PER_VEHICLE_KM,
    KpiDelta,
    KpiSnapshot,
    co2_grams,
    density_vehicles_per_km,
    snapshot_from_measured,
    snapshot_from_segments,
    travel_time_seconds,
)
from motion.domain.population import segment_target_vehicle_count
from motion.domain.traffic import TrafficSegment


def _segment(**overrides):
    values = {
        "description": "seg",
        "length_m": 1000.0,
        "speed_kmh": 36.0,
        "free_kmh": 50.0,
        "jam_factor": 4.0,
        "confidence": 1.0,
    }
    values.update(overrides)
    return TrafficSegment(**values)


def test_travel_time_seconds_basic() -> None:
    assert travel_time_seconds(1000.0, 36.0) == pytest.approx(100.0)


def test_travel_time_seconds_non_positive_length_is_zero() -> None:
    assert travel_time_seconds(0.0, 36.0) == 0.0
    assert travel_time_seconds(-5.0, 36.0) == 0.0


def test_travel_time_seconds_non_positive_speed_is_infinite() -> None:
    assert travel_time_seconds(1000.0, 0.0) == float("inf")
    assert travel_time_seconds(1000.0, -1.0) == float("inf")


def test_density_vehicles_per_km() -> None:
    assert density_vehicles_per_km(12, 2000.0) == pytest.approx(6.0)
    assert density_vehicles_per_km(12, 0.0) == 0.0


def test_co2_grams_uses_default_factor() -> None:
    assert co2_grams(10, 2.0) == pytest.approx(10 * 2.0 * DEFAULT_GRAMS_CO2_PER_VEHICLE_KM)


def test_co2_grams_is_overridable() -> None:
    assert co2_grams(10, 2.0, grams_per_vehicle_km=50.0) == pytest.approx(1000.0)


def test_snapshot_from_segments_empty_is_all_zero() -> None:
    assert snapshot_from_segments([]) == KpiSnapshot(0.0, 0.0, 0.0, 0, 0.0)


def test_snapshot_from_segments_matches_expected_values() -> None:
    # jam_factor=4 -> congestion 0.4 -> density 48 veh/km -> raw 48 over 1km -> capped at 40.
    # speed 36 km/h == 10 m/s -> 1000m in 100s.
    snapshot = snapshot_from_segments([_segment()])

    assert snapshot.corridor_travel_time_seconds == pytest.approx(100.0)
    assert snapshot.vehicle_count == 40
    assert snapshot.distance_km == pytest.approx(1.0)
    assert snapshot.average_density_vehicles_per_km == pytest.approx(40.0)
    assert snapshot.total_co2_grams == pytest.approx(40 * 1.0 * DEFAULT_GRAMS_CO2_PER_VEHICLE_KM)


def test_snapshot_from_segments_sums_travel_time_across_the_corridor() -> None:
    """Traversing the corridor crosses every segment, so the times add up.

    A mean would describe one average segment and could not be differenced
    against ``snapshot_from_measured``, which crosses the same total distance.
    """

    fast = _segment(length_m=1000.0, speed_kmh=36.0)  # 100s
    slow = _segment(length_m=1000.0, speed_kmh=18.0)  # 200s
    snapshot = snapshot_from_segments([fast, slow])

    assert snapshot.corridor_travel_time_seconds == pytest.approx(300.0)
    assert snapshot.distance_km == pytest.approx(2.0)


def test_snapshot_from_segments_applies_the_global_vehicle_budget() -> None:
    """The baseline count is what UC-01 would really mirror, not an uncapped sum.

    Ten fully-jammed 1 km segments each want the 40-vehicle per-segment cap;
    the simulator will only ever hold ``max_total_vehicles`` of them, and a
    baseline above that ceiling would make every density/CO2 delta measure the
    ceiling instead of the scenario.
    """

    segments = [_segment(jam_factor=10.0) for _ in range(10)]

    assert sum(segment_target_vehicle_count(s) for s in segments) == 400
    assert snapshot_from_segments(segments).vehicle_count == 80
    assert snapshot_from_segments(segments, max_total_vehicles=50).vehicle_count == 50


def test_snapshot_from_measured_with_no_observed_vehicles_is_all_zero() -> None:
    assert snapshot_from_measured(
        vehicle_count=0, average_speed_kmh=None, distance_km=5.0
    ) == KpiSnapshot(0.0, 0.0, 0.0, 0, 5.0)
    assert snapshot_from_measured(
        vehicle_count=5, average_speed_kmh=None, distance_km=5.0
    ) == KpiSnapshot(0.0, 0.0, 0.0, 0, 5.0)


def test_snapshot_from_measured_computes_from_average_speed() -> None:
    snapshot = snapshot_from_measured(vehicle_count=20, average_speed_kmh=36.0, distance_km=2.0)

    assert snapshot.corridor_travel_time_seconds == pytest.approx(200.0)
    assert snapshot.average_density_vehicles_per_km == pytest.approx(10.0)
    assert snapshot.total_co2_grams == pytest.approx(20 * 2.0 * DEFAULT_GRAMS_CO2_PER_VEHICLE_KM)
    assert snapshot.vehicle_count == 20
    assert snapshot.distance_km == 2.0


def test_kpi_delta_between_baseline_and_scenario() -> None:
    baseline = KpiSnapshot(100.0, 10.0, 1000.0, 10, 1.0)
    scenario = KpiSnapshot(150.0, 8.0, 800.0, 8, 1.0)

    delta = KpiDelta.between(baseline, scenario)

    assert delta == KpiDelta(
        travel_time_seconds=50.0, density_vehicles_per_km=-2.0, co2_grams=-200.0
    )
