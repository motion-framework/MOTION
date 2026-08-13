"""Executable evidence for inherited numerical behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from traffic_mirror.application.road_selection import (
    cut_road_around_midpoint,
    device_positions,
)
from traffic_mirror.domain.devices import DeviceReading
from traffic_mirror.domain.geography import (
    BoundingBox,
    approximate_geo_distance_meters,
    distance_point_to_line_segment,
    distance_point_to_polyline,
    planar_distance_meters,
    polyline_length_meters,
)
from traffic_mirror.domain.mirroring import SpeedMirrorPolicy, derive_target_vehicle_count
from traffic_mirror.domain.population import (
    derive_population_targets,
    segment_target_vehicle_count,
)
from traffic_mirror.domain.traffic import (
    TrafficIncident,
    TrafficSegment,
    enrich_segments_with_incidents,
)
from traffic_mirror.infrastructure.here.parser import TrafficParser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def segment(**overrides: object) -> TrafficSegment:
    values: dict[str, object] = {
        "description": "segment",
        "length_m": 100.0,
        "speed_kmh": 30.0,
        "free_kmh": 50.0,
        "jam_factor": 5.0,
        "confidence": 1.0,
    }
    values.update(overrides)
    return TrafficSegment(**values)  # type: ignore[arg-type]


def test_bounding_box_and_provider_serialization_baseline() -> None:
    bbox = BoundingBox.from_center(40.6772, 14.7604, 400)
    assert bbox.south_west_lat == pytest.approx(40.673606755300035)
    assert bbox.south_west_lon == pytest.approx(14.755662032934742)
    assert bbox.north_east_lat == pytest.approx(40.68079324469996)
    assert bbox.north_east_lon == pytest.approx(14.76513796706526)
    assert bbox.to_overpass_bbox() == (
        "14.755662032934742,40.673606755300035,14.76513796706526,40.68079324469996"
    )
    assert bbox.to_here_bbox() == f"bbox:{bbox.to_overpass_bbox()}"


def test_planar_and_approximate_distance_baseline() -> None:
    assert planar_distance_meters(0, 0, 3, 4) == 5.0
    assert distance_point_to_line_segment(1, 1, 0, 0, 2, 0) == 1.0
    assert distance_point_to_line_segment(3, 0, 0, 0, 2, 0) == 1.0
    assert distance_point_to_polyline(1, 1, [(0, 0), (2, 0)]) == 1.0
    assert polyline_length_meters([(0, 0), (3, 4), (6, 8)]) == 10.0
    assert approximate_geo_distance_meters((40, 14), (40.001, 14)) == pytest.approx(
        111.31999999974056
    )


def test_here_parser_units_fallbacks_and_skip_baseline() -> None:
    raw = json.loads((FIXTURES / "here" / "flow.json").read_text(encoding="utf-8"))
    segments = TrafficParser((1.0, 2.0)).parse(raw)
    assert len(segments) == 2
    first, fallback = segments
    assert first.description == "Via Baseline"
    assert first.speed_kmh == 28.8
    assert first.free_kmh == 64.8
    assert first.jam_factor == 6.0
    assert first.functional_class == 3
    assert fallback.speed_kmh == fallback.free_kmh == 18.0
    assert (fallback.lat, fallback.lon, fallback.shape_points) == (1.0, 2.0, ())


def test_incident_enrichment_baseline() -> None:
    original = segment(lat=40.0, lon=14.0, road_closure=False)
    nearby = TrafficIncident("x", "accident", "major", True, 40.0005, 14.0)
    enriched = enrich_segments_with_incidents([original], [nearby])[0]
    assert enriched.incidents_nearby == 1
    assert enriched.road_closure is True


def test_population_rounding_baseline_is_retained() -> None:
    assert segment_target_vehicle_count(segment(length_m=1_000, jam_factor=10)) == 40
    assert (
        segment_target_vehicle_count(segment(length_m=100, jam_factor=0, road_closure=True)) == 12
    )
    scaled = derive_population_targets(
        [segment(description=str(index), length_m=1_000, jam_factor=10) for index in range(3)],
        80,
    )
    # Inherited independent rounding produces 81 despite a nominal cap of 80.
    assert [count for _, count in scaled] == [27, 27, 27]
    assert sum(count for _, count in scaled) == 81


def test_device_fallback_population_baseline() -> None:
    assert derive_target_vehicle_count([]) == 20
    assert derive_target_vehicle_count([DeviceReading("a", 3, 1)]) == 20
    assert derive_target_vehicle_count([DeviceReading("a", 15, 1)]) == 75
    assert derive_target_vehicle_count([DeviceReading("a", 100, 1)]) == 80


def test_speed_policy_baseline() -> None:
    policy = SpeedMirrorPolicy(50)
    free = policy.command_for(segment(speed_kmh=60, free_kmh=70, jam_factor=1))
    assert free.target_speed_kmh == 60
    assert free.slowdown_percentage == pytest.approx(14.285714285714285)
    jam = policy.command_for(segment(speed_kmh=10, free_kmh=50, jam_factor=8, incidents_nearby=1))
    assert jam.target_speed_kmh == 10
    assert jam.follow_distance_meters == 8
    assert jam.ignore_vehicles_percentage == 5
    closure = policy.command_for(segment(road_closure=True))
    assert closure.target_speed_kmh == 0
    assert closure.slowdown_percentage == 100
    assert closure.is_held_at_closure is True
    assert policy.fallback_command().target_speed_kmh == 40


def test_road_cut_and_device_position_baseline() -> None:
    points = ((40.0, 14.0), (40.001, 14.0), (40.002, 14.0), (40.003, 14.0))
    cut = cut_road_around_midpoint(points, 70)
    assert cut == pytest.approx(
        [
            (40.000871182177505, 14.0),
            (40.001, 14.0),
            (40.002, 14.0),
            (40.002128817822495, 14.0),
        ]
    )
    road = segment(shape_points=points)
    assert device_positions(road, 4, BoundingBox(39, 13, 41, 15)) == list(points)
