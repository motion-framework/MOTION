from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from traffic_mirror.domain.geography import BoundingBox
from traffic_mirror.domain.maps import MapProfile
from traffic_mirror.domain.traffic import TrafficSegment
from traffic_mirror.infrastructure.carla.calibration import check_loaded_world


class FakeProjector:
    def to_xy(self, latitude_deg: float, longitude_deg: float) -> tuple[float, float]:
        return latitude_deg, longitude_deg


class FakeLocation:
    def __init__(self, x: float, y: float, z: float) -> None:
        self.x = x
        self.y = y
        self.z = z


class FakeColor:
    def __init__(self, red: int, green: int, blue: int) -> None:
        self.rgb = (red, green, blue)


class FakeMap:
    def get_waypoint(self, location, *, project_to_road):
        assert project_to_road is True
        road_x = location.x + (10.0 if location.x == 40.002 else 0.0)
        return SimpleNamespace(
            transform=SimpleNamespace(location=FakeLocation(road_x, location.y, 0.0))
        )


class FakeDebug:
    def __init__(self) -> None:
        self.points = []
        self.strings = []

    def draw_point(self, location, **options) -> None:
        self.points.append((location, options))

    def draw_string(self, location, label, **options) -> None:
        self.strings.append((location, label, options))


def test_calibration_checks_device_and_here_points_and_draws_opt_in_markers() -> None:
    profile = MapProfile(
        name="calibration",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        osm_path=Path("map.osm"),
        xodr_path=Path("map.xodr"),
        device_registry={"D1": (40.001, 14.001)},
    )
    segment = TrafficSegment(
        description="Via Test",
        length_m=100.0,
        speed_kmh=20.0,
        free_kmh=40.0,
        jam_factor=2.0,
        confidence=1.0,
        shape_points=(
            (40.0015, 14.0015),
            (40.002, 14.002),
            (41.0, 15.0),
        ),
    )
    debug = FakeDebug()
    world = SimpleNamespace(get_map=lambda: FakeMap(), debug=debug)
    carla_module = SimpleNamespace(Location=FakeLocation, Color=FakeColor)

    result = check_loaded_world(
        world=world,
        carla_module=carla_module,
        profile=profile,
        projector=FakeProjector(),
        segments=[segment],
        visual=True,
    )

    assert result.checked_points == 3
    assert result.failed_points == 1
    assert result.passed is False
    assert len(debug.points) == 3
    assert [item[1] for item in debug.strings] == [
        "D1",
        "segment-0-point-0",
        "segment-0-point-1",
    ]
