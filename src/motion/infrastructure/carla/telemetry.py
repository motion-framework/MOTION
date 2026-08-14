"""Explicit CARLA telemetry collection for behavioral datasets.

The collector attaches collision sensors only to the ScenarioRunner vehicles
present at session start and owns only those sensors.  Vehicle actors are never
destroyed.  ``weather_rain`` is the one deliberate schema completion versus
the legacy collector: it records CARLA precipitation so the current prediction
feature contract can be consumed without undocumented imputation.
"""

from __future__ import annotations

import csv
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from motion.config.settings import AppSettings, CarlaSettings
from motion.prediction.schema import RAW_REQUIRED_COLUMNS, validate_feature_value

from .kinematics import vehicle_speed_kmh
from .lifecycle import CarlaLifecycle

DEFAULT_DURATION_SECONDS: Final[float] = 180.0
DEFAULT_SAMPLING_INTERVAL_SECONDS: Final[float] = 0.5
VEHICLE_DISCOVERY_POLL_SECONDS: Final[float] = 0.5
VEHICLE_PATTERN: Final[str] = "vehicle.*"
COLLISION_SENSOR_BLUEPRINT: Final[str] = "sensor.other.collision"
TELEMETRY_COLUMNS: Final[tuple[str, ...]] = (*RAW_REQUIRED_COLUMNS, "weather_rain")

logger = logging.getLogger(__name__)


class TelemetryCollectionError(RuntimeError):
    """Raised when a CARLA session cannot produce a telemetry artifact."""


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    timestamp: float
    v_id: int
    x: float
    y: float
    speed_kmh: float
    throttle: float
    brake: float
    steer: float
    collision: int
    weather_rain: float

    def as_row(self) -> dict[str, float | int]:
        return {
            "timestamp": self.timestamp,
            "v_id": self.v_id,
            "x": self.x,
            "y": self.y,
            "speed_kmh": self.speed_kmh,
            "throttle": self.throttle,
            "brake": self.brake,
            "steer": self.steer,
            "collision": self.collision,
            "weather_rain": self.weather_rain,
        }


class CarlaTelemetryCollector:
    """Collect one bounded session from an already loaded CARLA world."""

    def __init__(
        self,
        *,
        world: Any,
        carla_module: ModuleType,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._world = world
        self._carla = carla_module
        self._monotonic_clock = monotonic_clock
        self._sleep = sleep
        self._initial_vehicles: tuple[Any, ...] = ()
        self._owned_sensors: list[Any] = []
        self._collided_vehicle_ids: set[int] = set()
        self._samples: list[TelemetrySample] = []
        self._closed = False

    @property
    def samples(self) -> tuple[TelemetrySample, ...]:
        return tuple(self._samples)

    def wait_for_initial_vehicles(
        self,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> tuple[Any, ...]:
        """Poll like the legacy ScenarioRunner collector until vehicles exist."""

        should_stop = stop_requested or (lambda: False)
        while not should_stop():
            vehicles = tuple(
                actor
                for actor in self._world.get_actors().filter(VEHICLE_PATTERN)
                if actor.is_alive
            )
            if vehicles:
                self._initial_vehicles = vehicles
                return vehicles
            self._sleep(VEHICLE_DISCOVERY_POLL_SECONDS)
        return ()

    def attach_collision_sensors(self, vehicles: Sequence[Any]) -> int:
        if self._closed:
            raise RuntimeError("CARLA telemetry collector is closed")
        collision_blueprint = self._world.get_blueprint_library().find(COLLISION_SENSOR_BLUEPRINT)
        for vehicle in vehicles:
            sensor = self._world.spawn_actor(
                collision_blueprint,
                self._carla.Transform(),
                attach_to=vehicle,
            )
            self._owned_sensors.append(sensor)
            sensor.listen(self._record_collision)
        return len(self._owned_sensors)

    def _record_collision(self, event: Any) -> None:
        self._collided_vehicle_ids.add(int(event.actor.id))

    def record(
        self,
        *,
        duration_seconds: float,
        sampling_interval_seconds: float,
        stop_requested: Callable[[], bool] | None = None,
    ) -> tuple[TelemetrySample, ...]:
        _validate_collection_window(duration_seconds, sampling_interval_seconds)
        if not self._initial_vehicles:
            raise TelemetryCollectionError(
                "Collision sensors must be attached after initial vehicle discovery"
            )

        should_stop = stop_requested or (lambda: False)
        started_at = self._monotonic_clock()
        last_recorded_at = 0.0
        while not should_stop():
            elapsed_seconds = self._monotonic_clock() - started_at
            # Strictly greater preserves the legacy duration boundary.
            if elapsed_seconds > duration_seconds:
                break
            active_vehicles = tuple(
                vehicle for vehicle in self._initial_vehicles if vehicle.is_alive
            )
            if not active_vehicles:
                break

            self._world.wait_for_tick()
            if elapsed_seconds - last_recorded_at < sampling_interval_seconds:
                continue

            precipitation = validate_feature_value(
                "weather_rain", float(self._world.get_weather().precipitation)
            )
            for vehicle in active_vehicles:
                self._samples.append(
                    self._sample_vehicle(
                        vehicle,
                        elapsed_seconds=elapsed_seconds,
                        weather_rain=precipitation,
                    )
                )
            last_recorded_at = elapsed_seconds
        return self.samples

    def _sample_vehicle(
        self,
        vehicle: Any,
        *,
        elapsed_seconds: float,
        weather_rain: float,
    ) -> TelemetrySample:
        location = vehicle.get_transform().location
        control = vehicle.get_control()
        return TelemetrySample(
            timestamp=round(elapsed_seconds, 2),
            v_id=int(vehicle.id),
            x=round(float(location.x), 2),
            y=round(float(location.y), 2),
            speed_kmh=round(vehicle_speed_kmh(vehicle), 2),
            throttle=round(float(control.throttle), 3),
            brake=round(float(control.brake), 3),
            steer=round(float(control.steer), 3),
            collision=int(vehicle.id in self._collided_vehicle_ids),
            weather_rain=round(weather_rain, 1),
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for sensor in reversed(self._owned_sensors):
            if not sensor.is_alive:
                continue
            try:
                stop = getattr(sensor, "stop", None)
                if callable(stop):
                    stop()
                sensor.destroy()
            except RuntimeError as error:
                logger.warning(
                    "Could not clean up owned collision sensor (sensor_id=%s, cause=%s)",
                    getattr(sensor, "id", "unknown"),
                    type(error).__name__,
                )

    def __enter__(self) -> CarlaTelemetryCollector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()


def telemetry_output_path(
    output: Path,
    *,
    timestamp: datetime,
) -> Path:
    """Treat a ``.csv`` output as a file and every other path as a directory."""

    if output.suffix.lower() == ".csv":
        return output
    return output / f"dataset_collisions_{timestamp:%Y%m%d_%H%M%S}.csv"


def write_telemetry_csv(path: Path, samples: Sequence[TelemetrySample]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(TELEMETRY_COLUMNS))
        writer.writeheader()
        writer.writerows(sample.as_row() for sample in samples)
    return path


def collect_telemetry(
    *,
    settings: AppSettings,
    output: Path,
    duration_seconds: float = DEFAULT_DURATION_SECONDS,
    sampling_interval_seconds: float = DEFAULT_SAMPLING_INTERVAL_SECONDS,
    lifecycle_factory: Callable[[CarlaSettings], CarlaLifecycle] = CarlaLifecycle,
    monotonic_clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    stop_requested: Callable[[], bool] | None = None,
) -> Path:
    """Collect telemetry from the current world and return the written CSV path."""

    _validate_collection_window(duration_seconds, sampling_interval_seconds)
    output_path = telemetry_output_path(
        output,
        timestamp=datetime.fromtimestamp(wall_clock()),
    )
    lifecycle = lifecycle_factory(settings.carla)
    collector: CarlaTelemetryCollector | None = None
    artifact_written = False
    try:
        lifecycle.start_server_if_configured()
        lifecycle.wait_until_ready()
        client = lifecycle.connect()
        collector = CarlaTelemetryCollector(
            world=client.get_world(),
            carla_module=lifecycle.carla,
            monotonic_clock=monotonic_clock,
            sleep=sleep,
        )
        vehicles = collector.wait_for_initial_vehicles(stop_requested=stop_requested)
        if not vehicles:
            raise TelemetryCollectionError(
                "Telemetry collection stopped before any CARLA vehicle was detected"
            )
        collector.attach_collision_sensors(vehicles)
        collector.record(
            duration_seconds=duration_seconds,
            sampling_interval_seconds=sampling_interval_seconds,
            stop_requested=stop_requested,
        )
        if not collector.samples:
            raise TelemetryCollectionError("No CARLA telemetry samples were produced")
        write_telemetry_csv(output_path, collector.samples)
        artifact_written = True
        return output_path
    finally:
        # Preserve the useful legacy behavior of saving partial observations
        # even if CARLA disconnects or the operator interrupts the session.
        if collector is not None and collector.samples and not artifact_written:
            try:
                write_telemetry_csv(output_path, collector.samples)
            except OSError as error:
                logger.error(
                    "Could not persist partial CARLA telemetry (cause=%s)",
                    type(error).__name__,
                )
        if collector is not None:
            collector.close()
        lifecycle.close()


def _validate_collection_window(
    duration_seconds: float,
    sampling_interval_seconds: float,
) -> None:
    if duration_seconds <= 0.0:
        raise ValueError("duration_seconds must be positive")
    if sampling_interval_seconds <= 0.0:
        raise ValueError("sampling_interval_seconds must be positive")
    if sampling_interval_seconds > duration_seconds:
        raise ValueError("sampling_interval_seconds must not exceed duration_seconds")
