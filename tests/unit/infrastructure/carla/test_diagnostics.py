from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

from traffic_mirror.config.paths import ProjectPaths
from traffic_mirror.config.settings import (
    AppSettings,
    CarlaSettings,
    HereSettings,
    MirrorSettings,
    OsmSettings,
)
from traffic_mirror.infrastructure.carla.diagnostics import (
    SpeedUnitDiagnosticConfig,
    SpeedUnitVerdict,
    classify_speed_unit,
    run_speed_unit_diagnostic,
)


class FakeLocation:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z


class FakeRotation:
    def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
        self.pitch, self.yaw, self.roll = pitch, yaw, roll


class FakeTransform:
    def __init__(self, location=None, rotation=None):
        self.location = location or FakeLocation()
        self.rotation = rotation or FakeRotation()


class FakeWaypoint:
    def __init__(self):
        self.transform = FakeTransform(rotation=FakeRotation(yaw=0.0))

    def next(self, _distance):
        return [self]


class FakeMap:
    def __init__(self):
        self.spawn_point = FakeTransform()
        self.waypoint = FakeWaypoint()

    def get_spawn_points(self):
        return [self.spawn_point]

    def get_waypoint(self, _location):
        return self.waypoint


class FakeVehicle:
    def __init__(self):
        self.id = 88
        self.is_alive = True
        self.velocity = SimpleNamespace(x=30.0 / 3.6, y=0.0, z=0.0)
        self.autopilot_calls = []
        self.destroyed = False

    def set_autopilot(self, enabled, port):
        self.autopilot_calls.append((enabled, port))

    def get_velocity(self):
        return self.velocity

    def destroy(self):
        self.destroyed = True
        self.is_alive = False


class FakeSpectator:
    def __init__(self):
        self.transform = None

    def set_transform(self, transform):
        self.transform = transform


class FakeBlueprintLibrary:
    def filter(self, identifier):
        assert identifier == "vehicle.tesla.model3"
        return [identifier]


class FakeWorld:
    def __init__(self):
        self.map = FakeMap()
        self.vehicle = FakeVehicle()
        self.spectator = FakeSpectator()

    def get_map(self):
        return self.map

    def get_blueprint_library(self):
        return FakeBlueprintLibrary()

    def spawn_actor(self, _blueprint, _spawn_point):
        return self.vehicle

    def get_spectator(self):
        return self.spectator


class FakeTrafficManager:
    def __init__(self):
        self.commands = []

    def set_desired_speed(self, vehicle, speed):
        self.commands.append((vehicle.id, speed))


class FakeCarla:
    Location = FakeLocation
    Rotation = FakeRotation
    Transform = FakeTransform


class FakeClient:
    def __init__(self, world, manager):
        self.world = world
        self.manager = manager

    def get_world(self):
        return self.world

    def get_trafficmanager(self, port):
        assert port == 8000
        return self.manager


class FakeLifecycle:
    def __init__(self, world, manager):
        self.carla = FakeCarla()
        self.client = FakeClient(world, manager)
        self.closed = False

    def start_server_if_configured(self):
        return False

    def wait_until_ready(self):
        return "fake"

    def connect(self):
        return self.client

    def close(self):
        self.closed = True


def settings(root: Path) -> AppSettings:
    return AppSettings(
        paths=ProjectPaths(root),
        carla=CarlaSettings(),
        here=HereSettings(),
        osm=OsmSettings(),
        mirror=MirrorSettings(),
    )


def test_speed_unit_verdict_preserves_strict_boundaries() -> None:
    assert (
        classify_speed_unit(peak_speed_kmh=30.0, commanded_value=30.0)
        is SpeedUnitVerdict.KILOMETERS_PER_HOUR
    )
    assert (
        classify_speed_unit(peak_speed_kmh=79.0, commanded_value=30.0)
        is SpeedUnitVerdict.METERS_PER_SECOND
    )
    assert (
        classify_speed_unit(peak_speed_kmh=78.0, commanded_value=30.0) is SpeedUnitVerdict.UNCLEAR
    )


def test_public_diagnostic_commands_and_always_removes_owned_vehicle(
    tmp_path: Path,
) -> None:
    world = FakeWorld()
    manager = FakeTrafficManager()
    lifecycle = FakeLifecycle(world, manager)
    stream = io.StringIO()
    sleeps = []

    exit_code = run_speed_unit_diagnostic(
        settings(tmp_path),
        config=SpeedUnitDiagnosticConfig(
            watch_seconds=2,
            look_seconds_after=0,
            waypoint_steps=2,
        ),
        lifecycle_factory=lambda _settings: lifecycle,
        sleep=sleeps.append,
        stream=stream,
    )

    assert exit_code == 0
    assert manager.commands == [(88, 30.0)]
    assert world.vehicle.autopilot_calls == [(True, 8000), (False, 8000)]
    assert world.vehicle.destroyed is True
    assert sleeps == [1.0, 1.0]
    assert "VERDICT: KM/H" in stream.getvalue()
    assert lifecycle.closed is True
