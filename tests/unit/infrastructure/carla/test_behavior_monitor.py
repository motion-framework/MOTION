from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import motion.infrastructure.carla.behavior_monitor as behavior_monitor
from motion.infrastructure.carla.behavior_monitor import (
    CarlaBehaviorMonitor,
    load_behavior_model,
)
from motion.prediction.inference import VehiclePrediction


class FakeLocation:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    def distance(self, other):
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2) ** 0.5


class FakeVehicle:
    def __init__(self, actor_id, *, x=0.0, speed_kmh=10.0):
        self.id = actor_id
        self.is_alive = True
        self.location = FakeLocation(x=x)
        self.velocity = SimpleNamespace(x=speed_kmh / 3.6, y=0.0, z=0.0)
        self.control = SimpleNamespace(throttle=0.2, brake=0.0, steer=0.0)
        self.autopilot_calls = []
        self.destroyed = False
        self.physics = SimpleNamespace(center_of_mass=None)

    def get_velocity(self):
        return self.velocity

    def get_control(self):
        return self.control

    def get_location(self):
        return self.location

    def get_transform(self):
        return SimpleNamespace(location=self.location)

    def set_autopilot(self, enabled, port):
        self.autopilot_calls.append((enabled, port))

    def get_physics_control(self):
        return self.physics

    def apply_physics_control(self, physics):
        self.physics = physics

    def destroy(self):
        self.destroyed = True
        self.is_alive = False


class FakeActors(list):
    def filter(self, _pattern):
        return list(self)


class FakeMap:
    name = "OpenDriveMap"

    def __init__(self):
        self.spawn_points = [
            SimpleNamespace(
                location=FakeLocation(),
                rotation=SimpleNamespace(yaw=0.0),
            )
        ]

    def get_spawn_points(self):
        return list(self.spawn_points)


class FakeBlueprintLibrary:
    def filter(self, _pattern):
        return ["vehicle-blueprint"]


class FakeDebug:
    def __init__(self):
        self.arrows = []

    def draw_arrow(self, *args, **kwargs):
        self.arrows.append((args, kwargs))


class FakeWorld:
    def __init__(self, vehicles, clock):
        self.actors = FakeActors(vehicles)
        self.clock = clock
        self.map = FakeMap()
        self.debug = FakeDebug()
        self.spawned = []

    def wait_for_tick(self):
        self.clock[0] += 1.0

    def get_actors(self):
        return self.actors

    def get_weather(self):
        return SimpleNamespace(precipitation=15.0)

    def get_blueprint_library(self):
        return FakeBlueprintLibrary()

    def get_map(self):
        return self.map

    def try_spawn_actor(self, _blueprint, _spawn_point):
        vehicle = FakeVehicle(99, x=20.0)
        self.spawned.append(vehicle)
        self.actors.append(vehicle)
        return vehicle


class FakeCarla:
    Location = FakeLocation

    class Color:
        def __init__(self, red, green, blue):
            self.rgb = red, green, blue

    class Vector3D:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z


class FakeTrafficManager:
    def __init__(self):
        self.distance = None
        self.speed_differences = []

    def set_global_distance_to_leading_vehicle(self, distance):
        self.distance = distance

    def vehicle_percentage_speed_difference(self, vehicle, percentage):
        self.speed_differences.append((vehicle.id, percentage))


class FakePredictor:
    def __init__(self, risky_vehicle_id=None):
        self.risky_vehicle_id = risky_vehicle_id

    def predict(self, observation):
        return VehiclePrediction(
            vehicle_id=observation.vehicle_id,
            incident_detected=observation.vehicle_id == self.risky_vehicle_id,
        )


class FailingPredictor:
    def predict(self, _observation):
        raise RuntimeError("systemic model failure")


def performance_clock():
    value = [0.0]

    def read():
        value[0] += 0.001
        return value[0]

    return read


def test_monitor_opens_and_confirms_alert_with_current_prediction_contract(
    tmp_path: Path,
) -> None:
    clock = [0.0]
    risky = FakeVehicle(1, x=0.0, speed_kmh=10.0)
    nearby = FakeVehicle(2, x=1.0, speed_kmh=10.0)
    world = FakeWorld([risky, nearby], clock)
    stats_path = tmp_path / "stats.txt"
    monitor = CarlaBehaviorMonitor(
        world=world,
        carla_module=FakeCarla(),
        traffic_manager=FakeTrafficManager(),
        predictor=FakePredictor(risky_vehicle_id=1),
        traffic_manager_port=8000,
        scenario_name="salerno",
        stats_path=stats_path,
        standalone=False,
        monotonic_clock=lambda: clock[0],
        wall_clock=lambda: 0.0,
        performance_clock=performance_clock(),
    )

    first_events = monitor.run_tick()
    risky.control.brake = 0.9
    risky.velocity.x = 1.0 / 3.6
    second_events = monitor.run_tick()
    monitor.close()

    assert [event.event_type.value for event in first_events] == ["started"]
    assert [event.event_type.value for event in second_events] == ["confirmed"]
    assert monitor.state.total_alerts == 1
    assert monitor.state.true_positives == 1
    assert len(world.debug.arrows) == 2
    report = stats_path.read_text(encoding="utf-8")
    assert "Total AI alerts: 1" in report
    assert "Confirmed incidents (TP): 1" in report
    assert "Mean Inference Latency: 1.00 ms" in report
    assert risky.destroyed is False
    assert nearby.destroyed is False


def test_standalone_monitor_cleans_only_vehicle_it_spawned(tmp_path: Path) -> None:
    clock = [0.0]
    external = FakeVehicle(1)
    world = FakeWorld([external], clock)
    monitor = CarlaBehaviorMonitor(
        world=world,
        carla_module=FakeCarla(),
        traffic_manager=FakeTrafficManager(),
        predictor=FakePredictor(),
        traffic_manager_port=8000,
        scenario_name="standalone",
        stats_path=tmp_path / "stats.txt",
        standalone=True,
        monotonic_clock=lambda: clock[0],
        wall_clock=lambda: 0.0,
        performance_clock=performance_clock(),
    )

    for _ in range(30):
        monitor.run_tick()

    assert monitor.owned_vehicle_ids == frozenset({99})
    monitor.close()
    assert world.spawned[0].destroyed is True
    assert world.spawned[0].autopilot_calls == [(True, 8000), (False, 8000)]
    assert external.destroyed is False


def test_predictor_failure_is_not_silenced(tmp_path: Path) -> None:
    clock = [0.0]
    world = FakeWorld([FakeVehicle(1)], clock)
    monitor = CarlaBehaviorMonitor(
        world=world,
        carla_module=FakeCarla(),
        traffic_manager=FakeTrafficManager(),
        predictor=FailingPredictor(),
        traffic_manager_port=8000,
        scenario_name="failure",
        stats_path=tmp_path / "stats.txt",
        standalone=False,
        monotonic_clock=lambda: clock[0],
        wall_clock=lambda: 0.0,
        performance_clock=performance_clock(),
    )

    with pytest.raises(RuntimeError, match="systemic model failure"):
        monitor.run_tick()
    monitor.close()


def test_model_loader_selects_modern_sidecars_without_legacy_deserialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "modern.pkl"
    metadata_path = tmp_path / "modern.pkl.metadata.json"
    metadata_path.write_text("{}", encoding="utf-8")
    expected_model = object()

    class FakeRepository:
        def __init__(self, path):
            assert path == model_path
            self.metadata_path = metadata_path
            self.checksum_path = tmp_path / "modern.pkl.sha256"

        def load(self):
            return SimpleNamespace(model=expected_model)

    monkeypatch.setattr(behavior_monitor, "JoblibModelRepository", FakeRepository)
    monkeypatch.setattr(
        behavior_monitor,
        "load_trusted_legacy_model",
        lambda *_args, **_kwargs: pytest.fail("legacy loader must not run"),
    )

    assert load_behavior_model(model_path) is expected_model


def test_model_loader_pins_bare_legacy_artifact_without_loading_real_pickle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "legacy.pkl"
    expected_model = object()
    captured = {}

    class FakeRepository:
        def __init__(self, path):
            assert path == model_path
            self.metadata_path = tmp_path / "missing.metadata.json"
            self.checksum_path = tmp_path / "missing.sha256"

    def fake_legacy_loader(path, *, expected_sha256):
        captured["path"] = path
        captured["sha256"] = expected_sha256
        return SimpleNamespace(model=expected_model)

    monkeypatch.setattr(behavior_monitor, "JoblibModelRepository", FakeRepository)
    monkeypatch.setattr(
        behavior_monitor,
        "load_trusted_legacy_model",
        fake_legacy_loader,
    )

    assert load_behavior_model(model_path) is expected_model
    assert captured == {
        "path": model_path,
        "sha256": behavior_monitor.LEGACY_REFERENCE_MODEL_SHA256,
    }
