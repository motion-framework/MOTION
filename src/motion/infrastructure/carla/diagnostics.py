"""Opt-in CARLA TrafficManager speed-unit diagnostic."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from types import ModuleType
from typing import Any, Final, TextIO

from motion.config.settings import AppSettings, CarlaSettings

from .kinematics import vehicle_speed_kmh
from .lifecycle import CarlaLifecycle

TESLA_MODEL_3_BLUEPRINT: Final[str] = "vehicle.tesla.model3"

logger = logging.getLogger(__name__)


class SpeedUnitVerdict(StrEnum):
    KILOMETERS_PER_HOUR = "km/h"
    METERS_PER_SECOND = "m/s"
    UNCLEAR = "unclear"


@dataclass(frozen=True, slots=True)
class SpeedUnitDiagnosticConfig:
    commanded_value: float = 30.0
    watch_seconds: int = 20
    look_seconds_after: int = 25
    waypoint_steps: int = 60
    waypoint_step_meters: float = 5.0
    maximum_yaw_change_degrees: float = 10.0
    camera_height_meters: float = 40.0

    def __post_init__(self) -> None:
        if self.commanded_value <= 0.0:
            raise ValueError("commanded_value must be positive")
        if self.watch_seconds <= 0:
            raise ValueError("watch_seconds must be positive")
        if self.look_seconds_after < 0:
            raise ValueError("look_seconds_after must be non-negative")
        if self.waypoint_steps <= 0 or self.waypoint_step_meters <= 0.0:
            raise ValueError("waypoint probing configuration must be positive")
        if self.maximum_yaw_change_degrees < 0.0:
            raise ValueError("maximum_yaw_change_degrees must be non-negative")


DEFAULT_DIAGNOSTIC_CONFIG: Final[SpeedUnitDiagnosticConfig] = SpeedUnitDiagnosticConfig()


@dataclass(frozen=True, slots=True)
class SpeedUnitDiagnosticResult:
    commanded_value: float
    peak_speed_kmh: float
    measured_speeds_kmh: tuple[float, ...]
    straight_length_meters: float
    verdict: SpeedUnitVerdict


class CarlaSpeedUnitDiagnostic:
    """Own exactly one diagnostic vehicle and always remove it."""

    def __init__(
        self,
        *,
        world: Any,
        carla_module: ModuleType,
        traffic_manager: Any,
        traffic_manager_port: int,
        config: SpeedUnitDiagnosticConfig = DEFAULT_DIAGNOSTIC_CONFIG,
        sleep: Callable[[float], None] = time.sleep,
        stream: TextIO | None = None,
    ) -> None:
        self._world = world
        self._carla = carla_module
        self._traffic_manager = traffic_manager
        self._traffic_manager_port = traffic_manager_port
        self._config = config
        self._sleep = sleep
        self._stream = stream or sys.stdout
        self._owned_vehicle: Any | None = None
        self._closed = False

    def run(self) -> SpeedUnitDiagnosticResult:
        if self._closed:
            raise RuntimeError("CARLA speed-unit diagnostic is closed")
        carla_map = self._world.get_map()
        spawn_point, straight_length = select_straightest_spawn_point(
            carla_map,
            config=self._config,
        )
        blueprints = list(self._world.get_blueprint_library().filter(TESLA_MODEL_3_BLUEPRINT))
        if not blueprints:
            raise ValueError(f"CARLA blueprint is unavailable: {TESLA_MODEL_3_BLUEPRINT}")

        try:
            vehicle = self._world.spawn_actor(blueprints[0], spawn_point)
            self._owned_vehicle = vehicle
            vehicle.set_autopilot(True, self._traffic_manager_port)
            self._traffic_manager.set_desired_speed(
                vehicle,
                self._config.commanded_value,
            )
            self._position_spectator(spawn_point)

            self._write(f"Spawn point has ~{straight_length:.0f} m straight ahead.\n")
            self._write(f"\nCar spawned. Commanded {self._config.commanded_value:.1f}.\n")
            measured: list[float] = []
            for second in range(self._config.watch_seconds):
                self._sleep(1.0)
                speed_kmh = vehicle_speed_kmh(vehicle)
                measured.append(speed_kmh)
                self._write(f"  {second + 1:2d}s: {speed_kmh:5.1f} km/h\n")

            peak = max(measured, default=0.0)
            verdict = classify_speed_unit(
                peak_speed_kmh=peak,
                commanded_value=self._config.commanded_value,
            )
            self._write_result(peak, verdict)

            for remaining in range(
                self._config.look_seconds_after,
                0,
                -1,
            ):
                self._write(f"  cleaning up in {remaining:2d}s...\r")
                self._sleep(1.0)
            return SpeedUnitDiagnosticResult(
                commanded_value=self._config.commanded_value,
                peak_speed_kmh=peak,
                measured_speeds_kmh=tuple(measured),
                straight_length_meters=straight_length,
                verdict=verdict,
            )
        finally:
            self.close()

    def _position_spectator(self, spawn_point: Any) -> None:
        location = spawn_point.location
        camera_location = self._carla.Location(
            x=location.x,
            y=location.y,
            z=location.z + self._config.camera_height_meters,
        )
        camera_rotation = self._carla.Rotation(
            pitch=-70.0,
            yaw=spawn_point.rotation.yaw,
        )
        self._world.get_spectator().set_transform(
            self._carla.Transform(camera_location, camera_rotation)
        )

    def _write_result(
        self,
        peak_speed_kmh: float,
        verdict: SpeedUnitVerdict,
    ) -> None:
        separator = "=" * 50
        self._write(f"\n{separator}\n")
        self._write(
            f"  Commanded: {self._config.commanded_value:.1f}"
            f"   |   Peak reached: {peak_speed_kmh:.1f} km/h\n"
        )
        self._write(separator + "\n")
        if verdict is SpeedUnitVerdict.KILOMETERS_PER_HOUR:
            self._write("  VERDICT: KM/H\n")
        elif verdict is SpeedUnitVerdict.METERS_PER_SECOND:
            self._write("  VERDICT: M/S -- divide by 3.6 in your code.\n")
        else:
            self._write(f"  UNCLEAR -- peak {peak_speed_kmh:.1f}. Inspect the per-second list.\n")
        self._write(separator + "\n")

    def _write(self, message: str) -> None:
        self._stream.write(message)
        self._stream.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        vehicle = self._owned_vehicle
        self._owned_vehicle = None
        if vehicle is None or not vehicle.is_alive:
            return
        try:
            vehicle.set_autopilot(False, self._traffic_manager_port)
            vehicle.destroy()
        except RuntimeError as error:
            logger.warning(
                "Could not clean up owned speed diagnostic vehicle (vehicle_id=%s, cause=%s)",
                getattr(vehicle, "id", "unknown"),
                type(error).__name__,
            )

    def __enter__(self) -> CarlaSpeedUnitDiagnostic:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()


def select_straightest_spawn_point(
    carla_map: Any,
    *,
    config: SpeedUnitDiagnosticConfig = DEFAULT_DIAGNOSTIC_CONFIG,
) -> tuple[Any, float]:
    """Preserve the legacy first-continuation/yaw-delta road probe."""

    spawn_points = list(carla_map.get_spawn_points())
    if not spawn_points:
        raise ValueError("The current CARLA map has no vehicle spawn points")
    best_point = spawn_points[0]
    best_length = 0.0
    for spawn_point in spawn_points:
        waypoint = carla_map.get_waypoint(spawn_point.location)
        if waypoint is None:
            continue
        length = 0.0
        current = waypoint
        for _ in range(config.waypoint_steps):
            continuations = current.next(config.waypoint_step_meters)
            if not continuations:
                break
            next_waypoint = continuations[0]
            if (
                abs(next_waypoint.transform.rotation.yaw - current.transform.rotation.yaw)
                > config.maximum_yaw_change_degrees
            ):
                break
            length += config.waypoint_step_meters
            current = next_waypoint
        if length > best_length:
            best_length = length
            best_point = spawn_point
    return best_point, best_length


def classify_speed_unit(
    *,
    peak_speed_kmh: float,
    commanded_value: float,
) -> SpeedUnitVerdict:
    """Classify using the original strict tolerance boundaries."""

    if abs(peak_speed_kmh - commanded_value) < 10.0:
        return SpeedUnitVerdict.KILOMETERS_PER_HOUR
    if abs(peak_speed_kmh - commanded_value * 3.6) < 30.0:
        return SpeedUnitVerdict.METERS_PER_SECOND
    return SpeedUnitVerdict.UNCLEAR


def run_speed_unit_diagnostic(
    settings: AppSettings,
    *,
    config: SpeedUnitDiagnosticConfig = DEFAULT_DIAGNOSTIC_CONFIG,
    lifecycle_factory: Callable[[CarlaSettings], CarlaLifecycle] = CarlaLifecycle,
    sleep: Callable[[float], None] = time.sleep,
    stream: TextIO | None = None,
) -> int:
    """Run the opt-in diagnostic against the currently loaded CARLA world."""

    lifecycle = lifecycle_factory(settings.carla)
    diagnostic: CarlaSpeedUnitDiagnostic | None = None
    try:
        lifecycle.start_server_if_configured()
        lifecycle.wait_until_ready()
        client = lifecycle.connect()
        diagnostic = CarlaSpeedUnitDiagnostic(
            world=client.get_world(),
            carla_module=lifecycle.carla,
            traffic_manager=client.get_trafficmanager(settings.carla.traffic_manager_port),
            traffic_manager_port=settings.carla.traffic_manager_port,
            config=config,
            sleep=sleep,
            stream=stream,
        )
        result = diagnostic.run()
        return int(result.verdict is not SpeedUnitVerdict.KILOMETERS_PER_HOUR)
    finally:
        if diagnostic is not None:
            diagnostic.close()
        lifecycle.close()
