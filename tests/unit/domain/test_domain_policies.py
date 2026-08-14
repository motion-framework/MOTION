from __future__ import annotations

from pathlib import Path

from motion.domain.devices import SyntheticDeviceProvider, synthesize_registry
from motion.domain.geography import BoundingBox
from motion.domain.maps import MapProfile
from motion.domain.mirroring import SpeedMirrorPolicy
from motion.domain.population import segment_target_vehicle_count
from motion.domain.traffic import TrafficSegment


class FixedRandom:
    def uniform(self, _start: float, _end: float) -> float:
        return -2.5

    def randint(self, _start: int, _end: int) -> int:
        return 7


def _segment(**overrides: object) -> TrafficSegment:
    values: dict[str, object] = {
        "description": "segment",
        "length_m": 100.0,
        "speed_kmh": 20.0,
        "free_kmh": 40.0,
        "jam_factor": 2.0,
        "confidence": 1.0,
    }
    values.update(overrides)
    return TrafficSegment(**values)  # type: ignore[arg-type]


def test_synthetic_device_contract_is_deterministic_with_injected_sources() -> None:
    profile = MapProfile(
        name="devices",
        bbox=BoundingBox(40.0, 14.0, 41.0, 15.0),
        osm_path=Path("map.osm"),
        xodr_path=Path("map.xodr"),
    )
    registry = synthesize_registry(profile)
    provider = SyntheticDeviceProvider(
        registry,
        random_source=FixedRandom(),  # type: ignore[arg-type]
        clock=lambda: 123.5,
    )

    readings = provider.poll()

    assert list(registry) == ["GEN_001", "GEN_002", "GEN_003", "GEN_004"]
    assert registry["GEN_001"] == (40.2, 14.2)
    assert [(item.device_id, item.count, item.speed_kmh, item.timestamp) for item in readings] == [
        ("GEN_001", 7, 27.5, 123.5),
        ("GEN_002", 7, 27.5, 123.5),
        ("GEN_003", 7, 27.5, 123.5),
        ("GEN_004", 7, 27.5, 123.5),
    ]


def test_map_profile_projection_origin_and_speed_policy_fallbacks() -> None:
    profile = MapProfile(
        name="override",
        bbox=BoundingBox(40.0, 14.0, 41.0, 15.0),
        osm_path=Path("map.osm"),
        xodr_path=Path("map.xodr"),
        geo_origin_override=(40.25, 14.75),
    )
    assert profile.geo_origin_lat == 40.25
    assert profile.geo_origin_lon == 14.75
    assert "+lat_0=40.25" in profile.proj_string
    assert "+lon_0=14.75" in profile.proj_string

    policy = SpeedMirrorPolicy(50.0)
    no_reference = policy.command_for(_segment(speed_kmh=100.0, free_kmh=0.0, jam_factor=3.1))
    assert no_reference.target_speed_kmh == 50.0
    assert no_reference.slowdown_percentage == 0.0
    assert no_reference.ignore_vehicles_percentage == 5

    stopped = policy.command_for(_segment(speed_kmh=0.0, free_kmh=100.0))
    assert stopped.slowdown_percentage == 85.0


def test_congestion_boundaries_and_population_clamping() -> None:
    assert _segment(jam_factor=2.999).congestion_level == "FREE"
    assert _segment(jam_factor=3.0).congestion_level == "SLOW"
    assert _segment(jam_factor=7.0).congestion_level == "JAM"
    assert segment_target_vehicle_count(_segment(jam_factor=-5.0)) == 0
    assert (
        segment_target_vehicle_count(_segment(length_m=10_000.0, jam_factor=10.0), max_vehicles=5)
        == 5
    )
