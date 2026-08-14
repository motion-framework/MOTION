from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from motion.config.paths import ProjectPaths
from motion.config.settings import (
    AppSettings,
    CarlaSettings,
    HereSettings,
    MirrorSettings,
    OsmSettings,
)
from motion.infrastructure.carla.telemetry import (
    TELEMETRY_COLUMNS,
    collect_telemetry,
    telemetry_output_path,
)


class FakeActorCollection(list):
    def filter(self, _pattern):
        return list(self)


class FakeVehicle:
    def __init__(self, actor_id=7):
        self.id = actor_id
        self.is_alive = True
        self.destroyed = False
        self._location = SimpleNamespace(x=12.345, y=67.891, z=0.0)
        self._velocity = SimpleNamespace(x=3.0, y=4.0, z=0.0)
        self._control = SimpleNamespace(throttle=0.1234, brake=0.0, steer=-0.2222)

    def get_transform(self):
        return SimpleNamespace(location=self._location)

    def get_velocity(self):
        return self._velocity

    def get_control(self):
        return self._control

    def destroy(self):
        self.destroyed = True
        self.is_alive = False


class FakeSensor:
    def __init__(self, sensor_id, parent):
        self.id = sensor_id
        self.parent = parent
        self.is_alive = True
        self.callback = None
        self.stopped = False
        self.destroyed = False

    def listen(self, callback):
        self.callback = callback

    def emit_collision(self):
        self.callback(SimpleNamespace(actor=self.parent))

    def stop(self):
        self.stopped = True

    def destroy(self):
        self.destroyed = True
        self.is_alive = False


class FakeBlueprintLibrary:
    def find(self, identifier):
        assert identifier == "sensor.other.collision"
        return identifier


class FakeWorld:
    def __init__(self, clock):
        self.clock = clock
        self.vehicle = FakeVehicle()
        self.sensors = []
        self.tick_count = 0

    def get_actors(self):
        return FakeActorCollection([self.vehicle])

    def get_blueprint_library(self):
        return FakeBlueprintLibrary()

    def spawn_actor(self, _blueprint, _transform, *, attach_to):
        sensor = FakeSensor(100 + len(self.sensors), attach_to)
        self.sensors.append(sensor)
        return sensor

    def wait_for_tick(self):
        self.tick_count += 1
        self.clock[0] += 0.5
        if self.tick_count == 3:
            self.sensors[0].emit_collision()

    def get_weather(self):
        return SimpleNamespace(precipitation=42.34)


class FakeCarla:
    class Transform:
        pass


class FakeClient:
    def __init__(self, world):
        self.world = world

    def get_world(self):
        return self.world


class FakeLifecycle:
    def __init__(self, world):
        self.carla = FakeCarla()
        self.client = FakeClient(world)
        self.started = False
        self.waited = False
        self.closed = False

    def start_server_if_configured(self):
        self.started = True
        return False

    def wait_until_ready(self):
        self.waited = True
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


def test_collect_telemetry_records_sticky_collision_weather_and_cleans_sensors(
    tmp_path: Path,
) -> None:
    clock = [0.0]
    world = FakeWorld(clock)
    lifecycle = FakeLifecycle(world)
    destination = tmp_path / "session.csv"

    result = collect_telemetry(
        settings=settings(tmp_path),
        output=destination,
        duration_seconds=1.0,
        sampling_interval_seconds=0.5,
        lifecycle_factory=lambda _settings: lifecycle,
        monotonic_clock=lambda: clock[0],
        wall_clock=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    assert result == destination
    with result.open(encoding="utf-8", newline="") as telemetry_file:
        reader = csv.DictReader(telemetry_file)
        rows = list(reader)
        assert tuple(reader.fieldnames or ()) == TELEMETRY_COLUMNS
    assert [row["collision"] for row in rows] == ["0", "1"]
    assert [row["timestamp"] for row in rows] == ["0.5", "1.0"]
    assert rows[0]["speed_kmh"] == "18.0"
    assert rows[0]["weather_rain"] == "42.3"
    assert world.sensors[0].stopped is True
    assert world.sensors[0].destroyed is True
    assert world.vehicle.destroyed is False
    assert lifecycle.started and lifecycle.waited and lifecycle.closed


def test_directory_output_gets_legacy_timestamped_filename(tmp_path: Path) -> None:
    result = telemetry_output_path(
        tmp_path,
        timestamp=datetime(2026, 8, 11, 12, 34, 56),
    )
    assert result == tmp_path / "dataset_collisions_20260811_123456.csv"
