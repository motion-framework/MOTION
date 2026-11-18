from __future__ import annotations

from pathlib import Path

from motion.application.traffic_providers import build_traffic_provider
from motion.domain.geography import BoundingBox
from motion.domain.maps import MapProfile


def test_offline_selection_never_builds_a_here_provider(monkeypatch) -> None:
    from motion.infrastructure.here import factory

    called = False

    def fail_if_here_is_built(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("HERE provider must not be built in offline mode")

    monkeypatch.setattr(factory, "build_here_provider", fail_if_here_is_built)

    profile = MapProfile(
        name="offline",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        osm_path=Path("map.osm"),
        xodr_path=Path("map.xodr"),
        device_registry={"D1": (40.001, 14.001), "D2": (40.002, 14.002)},
    )

    provider = build_traffic_provider(
        settings=object(), profile=profile, road_filter="", offline=True
    )
    segments = provider.fetch_segments()

    assert len(segments) == 1
    assert called is False


def test_live_selection_delegates_to_the_here_factory(monkeypatch) -> None:
    from motion.infrastructure.here import factory

    captured: dict[str, object] = {}
    sentinel_provider = object()

    def fake_build_here_provider(settings, profile, *, road_filter):
        captured["settings"] = settings
        captured["profile"] = profile
        captured["road_filter"] = road_filter
        return sentinel_provider

    monkeypatch.setattr(factory, "build_here_provider", fake_build_here_provider)

    profile = MapProfile(
        name="live",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        osm_path=Path("map.osm"),
        xodr_path=Path("map.xodr"),
    )
    settings = object()

    provider = build_traffic_provider(
        settings=settings, profile=profile, road_filter="main", offline=False
    )

    assert provider is sentinel_provider
    assert captured == {"settings": settings, "profile": profile, "road_filter": "main"}
