from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from motion.config.settings import CarlaSettings
from motion.infrastructure.carla.adapter import CarlaTrafficSimulator
from motion.infrastructure.carla.api import (
    CarlaUnavailableError,
    load_carla_module,
)
from motion.infrastructure.carla.lifecycle import CarlaLifecycle
from motion.infrastructure.carla.population import (
    CarlaPopulationManager,
    OwnedVehicleRegistry,
)


class FakeLocation:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    def distance(self, other):
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2) ** 0.5


class FakeActor:
    def __init__(self, actor_id, *, alive=True, location=None, velocity=None):
        self.id = actor_id
        self.is_alive = alive
        self._location = location or FakeLocation()
        self._velocity = velocity or FakeLocation()
        self.autopilot_calls = []

    def get_location(self):
        return self._location

    def get_velocity(self):
        return self._velocity

    def set_autopilot(self, enabled, port):
        self.autopilot_calls.append((enabled, port))


class FakeActorCollection(list):
    def filter(self, pattern):
        self.last_pattern = pattern
        return list(self)


class FakeBlueprintLibrary:
    def filter(self, pattern):
        self.last_pattern = pattern
        return []


class FakeMap:
    def get_spawn_points(self):
        return []

    def get_waypoint(self, location, project_to_road=True):
        del location, project_to_road
        return None


class FakeWorld:
    def __init__(self, actors):
        self.actors = FakeActorCollection(actors)
        self.map = FakeMap()

    def get_actors(self):
        return self.actors

    def get_blueprint_library(self):
        return FakeBlueprintLibrary()

    def get_map(self):
        return self.map


class FakeCommander:
    def __init__(self):
        self.disabled = []

    def disable_autopilot(self, vehicle):
        self.disabled.append(vehicle.id)
        return True

    def configure_new_vehicle(self, vehicle):
        del vehicle


class FakePinner:
    def pin(self, vehicle, points):
        del vehicle, points
        return True


class FakeTrafficManager:
    def set_synchronous_mode(self, enabled):
        del enabled

    def set_global_distance_to_leading_vehicle(self, distance_meters):
        del distance_meters

    def global_percentage_speed_difference(self, percentage):
        del percentage


class FakeClient:
    def __init__(self):
        self.timeout = None
        self.batches = []
        self.generated = None

    def set_timeout(self, timeout):
        self.timeout = timeout

    def get_server_version(self):
        return "0.9.16"

    def generate_opendrive_world(self, xml, parameters):
        self.generated = (xml, parameters)
        return "WORLD"

    def apply_batch_sync(self, commands, do_tick):
        self.batches.append((commands, do_tick))
        return []


class FakeCarlaModule:
    Location = FakeLocation

    class command:
        @staticmethod
        def DestroyActor(actor_id):
            return ("destroy", actor_id)

    class OpendriveGenerationParameters:
        def __init__(self, **values):
            self.values = values

    def __init__(self, client):
        self.client = client
        self.client_arguments = []

    def Client(self, host, port):
        self.client_arguments.append((host, port))
        return self.client


class CarlaBoundaryTest(unittest.TestCase):
    def test_importing_adapter_does_not_import_optional_carla_module(self):
        sys.modules.pop("carla", None)
        real_import = importlib.import_module
        requested = []

        def guarded_import(name, package=None):
            requested.append(name)
            if name == "carla":
                raise AssertionError("adapter imported CARLA eagerly")
            return real_import(name, package)

        with patch("importlib.import_module", side_effect=guarded_import):
            module = importlib.import_module("motion.infrastructure.carla.adapter")
        self.assertIsNotNone(module.CarlaTrafficSimulator)
        self.assertNotIn("carla", requested)

    def test_importing_legacy_capability_adapters_does_not_import_carla(self):
        sys.modules.pop("carla", None)
        real_import = importlib.import_module
        requested = []

        def guarded_import(name, package=None):
            requested.append(name)
            if name == "carla":
                raise AssertionError("capability adapter imported CARLA eagerly")
            return real_import(name, package)

        capability_modules = (
            "motion.infrastructure.carla.telemetry",
            "motion.infrastructure.carla.behavior_monitor",
            "motion.infrastructure.carla.diagnostics",
        )
        with patch("importlib.import_module", side_effect=guarded_import):
            imported = tuple(importlib.import_module(name) for name in capability_modules)

        self.assertTrue(all(imported))
        self.assertNotIn("carla", requested)
        self.assertNotIn("carla", sys.modules)

    def test_missing_carla_dependency_has_actionable_error(self):
        real_import = importlib.import_module

        def missing(name):
            if name == "carla":
                error = ModuleNotFoundError("No module named 'carla'")
                error.name = "carla"
                raise error
            return real_import(name)

        with (
            patch("importlib.import_module", side_effect=missing),
            self.assertRaises(CarlaUnavailableError),
        ):
            load_carla_module()

    def test_lifecycle_uses_centralized_120_second_timeout_and_loads_xodr(self):
        client = FakeClient()
        carla_module = FakeCarlaModule(client)
        settings = CarlaSettings(client_timeout_seconds=120.0)
        lifecycle = CarlaLifecycle(settings, carla_loader=lambda: carla_module)

        with tempfile.TemporaryDirectory() as temporary_directory:
            xodr = Path(temporary_directory) / "map.xodr"
            xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
            world = lifecycle.load_open_drive_world(xodr)

        self.assertEqual(world, "WORLD")
        self.assertEqual(client.timeout, 120.0)
        self.assertEqual(carla_module.client_arguments, [("localhost", 2000)])
        self.assertEqual(client.generated[0], "<OpenDRIVE/>")
        self.assertEqual(client.generated[1].values["max_road_length"], 50.0)

    def test_population_destroy_never_touches_external_actor(self):
        external = FakeActor(10)
        owned = FakeActor(20)
        world = FakeWorld([external, owned])
        client = FakeClient()
        carla_module = FakeCarlaModule(client)
        registry = OwnedVehicleRegistry()
        registry.register(owned)
        commander = FakeCommander()
        manager = CarlaPopulationManager(
            client=client,
            world=world,
            carla_module=carla_module,
            traffic_manager_port=8000,
            commander=commander,
            path_pinner=FakePinner(),
            registry=registry,
        )

        destroyed = manager.destroy([external, owned])

        self.assertEqual(destroyed, 1)
        self.assertEqual(client.batches, [([("destroy", 20)], True)])
        self.assertEqual(commander.disabled, [20])
        self.assertTrue(external.is_alive)
        self.assertEqual(registry.ids(), set())

    def _build_simulator(self, actors=()):
        world = FakeWorld(list(actors))
        client = FakeClient()
        carla_module = FakeCarlaModule(client)
        return CarlaTrafficSimulator(
            client=client,
            world=world,
            traffic_manager=FakeTrafficManager(),
            carla_module=carla_module,
            traffic_manager_port=8000,
            speed_limit_kmh=50.0,
        )

    def test_average_speed_is_none_with_no_owned_vehicles(self):
        simulator = self._build_simulator()

        self.assertIsNone(simulator.average_speed_kmh())

    def test_average_speed_measures_only_owned_live_vehicles(self):
        # 3-4-0 velocity vector -> sqrt(3^2+4^2) = 5 m/s -> 18.0 km/h.
        owned_fast = FakeActor(1, velocity=FakeLocation(3.0, 4.0, 0.0))
        # 6-8-0 velocity vector -> sqrt(6^2+8^2) = 10 m/s -> 36.0 km/h.
        owned_slow = FakeActor(2, velocity=FakeLocation(6.0, 8.0, 0.0))
        unowned = FakeActor(3, velocity=FakeLocation(100.0, 0.0, 0.0))
        simulator = self._build_simulator([owned_fast, owned_slow, unowned])
        simulator._registry.register(owned_fast)
        simulator._registry.register(owned_slow)

        self.assertAlmostEqual(simulator.average_speed_kmh(), (18.0 + 36.0) / 2, places=6)
        self.assertEqual(simulator.owned_vehicle_count(), 2)


if __name__ == "__main__":
    unittest.main()
