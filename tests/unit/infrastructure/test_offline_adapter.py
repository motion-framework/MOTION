from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from motion.domain.geography import BoundingBox
from motion.domain.maps import MapProfile
from motion.infrastructure.here.parser import IncidentParser, TrafficParser
from motion.infrastructure.offline import (
    HereCompatiblePayloadFactory,
    build_offline_provider,
)


class FixedRandom:
    def uniform(self, _start: float, _end: float) -> float:
        return 5.0


def profile() -> MapProfile:
    return MapProfile(
        name="contract",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        osm_path=Path("map.osm"),
        xodr_path=Path("map.xodr"),
        speed_limit_kmh=50.0,
        device_registry={
            "D1": (40.001, 14.001),
            "D2": (40.002, 14.002),
            "D3": (40.003, 14.003),
        },
    )


def test_synthetic_flow_payload_matches_consumed_here_v7_contract() -> None:
    active_profile = profile()
    factory = HereCompatiblePayloadFactory(
        active_profile,
        active_profile.device_registry,
        random_source=FixedRandom(),  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 8, 13, 15, 0, tzinfo=UTC),
    )

    payload = factory.flow_payload()

    assert payload["sourceUpdated"] == "2026-08-13T15:00:00Z"
    assert len(payload["results"]) == 2
    first = payload["results"][0]
    assert set(first) == {"location", "currentFlow"}
    assert set(first["currentFlow"]) == {
        "speed",
        "speedUncapped",
        "freeFlow",
        "jamFactor",
        "confidence",
        "traversability",
    }
    assert first["currentFlow"]["speed"] == pytest.approx(45.0 / 3.6, abs=1e-6)
    assert first["currentFlow"]["freeFlow"] == pytest.approx(50.0 / 3.6, abs=1e-6)
    assert first["currentFlow"]["jamFactor"] == 1.0
    link = first["location"]["shape"]["links"][0]
    assert set(link) == {"functionalClass", "points"}
    assert link["points"] == [
        {"lat": 40.001, "lng": 14.001},
        {"lat": 40.002, "lng": 14.002},
    ]

    # Contract proof: the production parsers accept both synthetic payloads.
    parsed = TrafficParser((40.0, 14.0)).parse(payload)
    assert len(parsed) == 2
    assert parsed[0].speed_kmh == 45.0
    assert parsed[0].free_kmh == 50.0
    assert IncidentParser((40.0, 14.0)).parse(factory.incident_payload()) == []


def test_offline_provider_uses_the_production_here_parsing_pipeline() -> None:
    active_profile = profile()
    provider = build_offline_provider(
        active_profile,
        active_profile.device_registry,
        random_source=FixedRandom(),  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 8, 13, 15, 0, tzinfo=UTC),
    )

    segments = provider.fetch_segments()

    assert [segment.description for segment in segments] == [
        "Synthetic contract segment 1",
        "Synthetic contract segment 2",
    ]
    assert all(segment.confidence == 0.9 for segment in segments)
    assert all(segment.functional_class == 3 for segment in segments)
    assert all(segment.shape_points for segment in segments)


def test_payload_factory_falls_back_to_map_bounds_without_device_points() -> None:
    active_profile = profile()
    factory = HereCompatiblePayloadFactory(
        active_profile,
        {},
        random_source=FixedRandom(),  # type: ignore[arg-type]
    )

    result = factory.flow_payload()["results"][0]

    assert result["location"]["shape"]["links"][0]["points"] == [
        {"lat": 40.0, "lng": 14.0},
        {"lat": 40.01, "lng": 14.01},
    ]
