"""CARLA adapter for the simulator-independent behavioral-risk contracts."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Protocol

from motion.config.runtime_state import load_active_map_state
from motion.config.settings import AppSettings, CarlaSettings
from motion.domain.maps import MapProfile
from motion.prediction.artifacts import (
    LEGACY_REFERENCE_MODEL_SHA256,
    JoblibModelRepository,
    load_trusted_legacy_model,
)
from motion.prediction.inference import (
    AlertEvent,
    AlertEventType,
    AlertTrackerState,
    TrackingSample,
    VehiclePrediction,
    VehicleRiskPredictor,
    alert_statistics,
    update_alert_tracker,
)
from motion.prediction.schema import VehicleObservation

from .kinematics import nearby_vehicle_count, vehicle_speed_kmh
from .lifecycle import CarlaLifecycle

TARGET_VEHICLE_COUNT: Final[int] = 80
SPAWN_TICK_INTERVAL: Final[int] = 30
NEARBY_VEHICLE_RADIUS_METERS: Final[float] = 15.0
GLOBAL_FOLLOW_DISTANCE_METERS: Final[float] = 1.5
STANDALONE_SPEED_DIFFERENCE_PERCENT: Final[float] = 30.0
STANDALONE_CENTER_OF_MASS_Z_METERS: Final[float] = -2.0
SPECTATOR_HEIGHT_METERS: Final[float] = 100.0
ALERT_ARROW_TOP_Z_METERS: Final[float] = 5.0
ALERT_ARROW_BOTTOM_Z_METERS: Final[float] = 2.0
REALTIME_BUDGET_MILLISECONDS: Final[float] = 500.0

logger = logging.getLogger(__name__)


class RiskPredictor(Protocol):
    def predict(self, observation: VehicleObservation) -> VehiclePrediction: ...


class CarlaBehaviorMonitor:
    """Translate current-world vehicle state into prediction tracking samples."""

    def __init__(
        self,
        *,
        world: Any,
        carla_module: ModuleType,
        traffic_manager: Any,
        predictor: RiskPredictor,
        traffic_manager_port: int,
        scenario_name: str,
        stats_path: Path,
        standalone: bool,
        random_source: random.Random | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        performance_clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._world = world
        self._carla = carla_module
        self._traffic_manager = traffic_manager
        self._predictor = predictor
        self._traffic_manager_port = traffic_manager_port
        self._scenario_name = scenario_name
        self._stats_path = stats_path
        self._standalone = standalone
        self._random = random_source or random.Random()
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._performance_clock = performance_clock
        self._started_at_seconds = monotonic_clock()
        self._tick_counter = 0
        self._state = AlertTrackerState()
        self._owned_vehicles: dict[int, Any] = {}
        self._closed = False

        self._traffic_manager.set_global_distance_to_leading_vehicle(GLOBAL_FOLLOW_DISTANCE_METERS)
        self._blueprints = list(world.get_blueprint_library().filter("vehicle.*"))
        self._spawn_points = list(world.get_map().get_spawn_points())
        self._random.shuffle(self._spawn_points)

    @property
    def state(self) -> AlertTrackerState:
        return self._state

    @property
    def owned_vehicle_ids(self) -> frozenset[int]:
        return frozenset(
            vehicle_id for vehicle_id, vehicle in self._owned_vehicles.items() if vehicle.is_alive
        )

    def run(
        self,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> AlertTrackerState:
        should_stop = stop_requested or (lambda: False)
        try:
            while not should_stop():
                self.run_tick()
            return self._state
        finally:
            self.close()

    def run_tick(self) -> tuple[AlertEvent, ...]:
        if self._closed:
            raise RuntimeError("CARLA behavior monitor is closed")

        self._world.wait_for_tick()
        self._tick_counter += 1
        observed_at = self._monotonic_clock()
        active_vehicles = tuple(
            vehicle for vehicle in self._world.get_actors().filter("vehicle.*") if vehicle.is_alive
        )
        weather_rain = round(
            float(self._world.get_weather().precipitation),
            1,
        )

        self._spawn_standalone_vehicle_if_due(len(active_vehicles))

        tick_events: list[AlertEvent] = []
        for vehicle in active_vehicles:
            try:
                observation = self._observation(vehicle, weather_rain)
            except RuntimeError as error:
                logger.warning(
                    "Could not observe CARLA vehicle (vehicle_id=%s, cause=%s)",
                    getattr(vehicle, "id", "unknown"),
                    type(error).__name__,
                )
                continue

            inference_started_at = self._performance_clock()
            prediction = self._predictor.predict(observation)
            inference_latency_ms = (self._performance_clock() - inference_started_at) * 1_000.0
            nearby_count = nearby_vehicle_count(
                vehicle,
                active_vehicles,
                radius_meters=NEARBY_VEHICLE_RADIUS_METERS,
            )
            self._state, events = update_alert_tracker(
                self._state,
                TrackingSample(
                    observation=observation,
                    prediction=prediction,
                    nearby_vehicle_count=nearby_count,
                    observed_at_seconds=observed_at,
                    inference_latency_ms=inference_latency_ms,
                ),
            )
            if prediction.incident_detected and nearby_count > 0:
                self._draw_alert(vehicle)
            if events:
                tick_events.extend(events)
                self._log_events(events)
                self._persist_statistics()
        return tuple(tick_events)

    def _observation(self, vehicle: Any, weather_rain: float) -> VehicleObservation:
        control = vehicle.get_control()
        return VehicleObservation(
            vehicle_id=int(vehicle.id),
            speed_kmh=vehicle_speed_kmh(vehicle),
            throttle=float(control.throttle),
            brake=float(control.brake),
            steer=float(control.steer),
            weather_rain=weather_rain,
        )

    def _spawn_standalone_vehicle_if_due(self, active_vehicle_count: int) -> None:
        if not self._standalone or active_vehicle_count >= TARGET_VEHICLE_COUNT:
            return
        if self._tick_counter < SPAWN_TICK_INTERVAL:
            return
        self._tick_counter = 0
        if not self._blueprints or not self._spawn_points:
            return
        vehicle = self._world.try_spawn_actor(
            self._random.choice(self._blueprints),
            self._random.choice(self._spawn_points),
        )
        if vehicle is None:
            return
        self._owned_vehicles[int(vehicle.id)] = vehicle
        try:
            vehicle.set_autopilot(True, self._traffic_manager_port)
            self._traffic_manager.vehicle_percentage_speed_difference(
                vehicle,
                STANDALONE_SPEED_DIFFERENCE_PERCENT,
            )
            physics = vehicle.get_physics_control()
            physics.center_of_mass = self._carla.Vector3D(
                0.0,
                0.0,
                STANDALONE_CENTER_OF_MASS_Z_METERS,
            )
            vehicle.apply_physics_control(physics)
        except Exception:
            self._destroy_owned_vehicle(vehicle)
            raise

    def _draw_alert(self, vehicle: Any) -> None:
        location = vehicle.get_transform().location
        top = self._carla.Location(
            x=location.x,
            y=location.y,
            z=location.z + ALERT_ARROW_TOP_Z_METERS,
        )
        bottom = self._carla.Location(
            x=location.x,
            y=location.y,
            z=location.z + ALERT_ARROW_BOTTOM_Z_METERS,
        )
        self._world.debug.draw_arrow(
            top,
            bottom,
            thickness=0.2,
            arrow_size=0.3,
            color=self._carla.Color(255, 0, 0),
            life_time=0.1,
        )

    @staticmethod
    def _log_events(events: Sequence[AlertEvent]) -> None:
        for event in events:
            if event.event_type is AlertEventType.STARTED:
                logger.warning("AI alert started (vehicle_id=%s)", event.vehicle_id)
            elif event.event_type is AlertEventType.CONFIRMED:
                logger.info(
                    "AI alert confirmed (vehicle_id=%s, lead_time_seconds=%.3f)",
                    event.vehicle_id,
                    event.lead_time_seconds or 0.0,
                )
            else:
                logger.info(
                    "AI alert expired as false positive (vehicle_id=%s)",
                    event.vehicle_id,
                )

    def _persist_statistics(self) -> None:
        elapsed_seconds = max(
            0.0,
            self._monotonic_clock() - self._started_at_seconds,
        )
        write_monitor_statistics(
            self._stats_path,
            state=self._state,
            scenario_name=self._scenario_name,
            duration_seconds=elapsed_seconds,
            timestamp_seconds=self._wall_clock(),
        )

    def _destroy_owned_vehicle(self, vehicle: Any) -> None:
        vehicle_id = int(vehicle.id)
        if vehicle_id not in self._owned_vehicles:
            return
        try:
            if vehicle.is_alive:
                vehicle.set_autopilot(False, self._traffic_manager_port)
                vehicle.destroy()
        except RuntimeError as error:
            logger.warning(
                "Could not clean up owned monitor vehicle (vehicle_id=%s, cause=%s)",
                vehicle_id,
                type(error).__name__,
            )
        finally:
            self._owned_vehicles.pop(vehicle_id, None)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._persist_statistics()
        finally:
            for vehicle in tuple(self._owned_vehicles.values()):
                self._destroy_owned_vehicle(vehicle)

    def __enter__(self) -> CarlaBehaviorMonitor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()


def write_monitor_statistics(
    path: Path,
    *,
    state: AlertTrackerState,
    scenario_name: str,
    duration_seconds: float,
    timestamp_seconds: float,
) -> Path:
    """Overwrite the legacy-compatible realtime validation summary."""

    statistics = alert_statistics(state)
    lines = [
        f"--- Real-Time validation log for {scenario_name.capitalize()} scenario ---",
        f"Timestamp: {time.ctime(timestamp_seconds)}",
        f"Test duration: {duration_seconds / 60.0:.2f} minutes",
        "-" * 40,
        f"Total AI alerts: {statistics.total_alerts}",
        f"Confirmed incidents (TP): {statistics.true_positives}",
        f"False alarms (FP): {statistics.false_positives}",
    ]
    if statistics.mean_lead_time_seconds is not None:
        lines.append(f"Mean prediction lead time: {statistics.mean_lead_time_seconds:.2f} seconds")
    if statistics.mean_inference_latency_ms is not None:
        lines.extend(
            (
                f"Mean Inference Latency: {statistics.mean_inference_latency_ms:.2f} ms",
                "Safety Margin for T=0.5s: "
                f"{REALTIME_BUDGET_MILLISECONDS - statistics.mean_inference_latency_ms:.2f} ms",
            )
        )
    if statistics.precision is not None:
        lines.append(f"Current real-time precision: {statistics.precision * 100.0:.2f}%")
    lines.append("-" * 40)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_behavior_model(model_path: Path) -> Any:
    """Load modern sidecar artifacts or the single pinned legacy reference."""

    repository = JoblibModelRepository(model_path)
    if repository.metadata_path.is_file() or repository.checksum_path.is_file():
        return repository.load().model
    return load_trusted_legacy_model(
        model_path,
        expected_sha256=LEGACY_REFERENCE_MODEL_SHA256,
    ).model


def run_behavior_monitor(
    *,
    settings: AppSettings,
    model_path: Path,
    stats_path: Path,
    lifecycle_factory: Callable[[CarlaSettings], CarlaLifecycle] = CarlaLifecycle,
    model_loader: Callable[[Path], Any] = load_behavior_model,
    stop_requested: Callable[[], bool] | None = None,
    random_source: random.Random | None = None,
    monotonic_clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    performance_clock: Callable[[], float] = time.perf_counter,
) -> int:
    """Compose the verified model with the current or active-map CARLA world."""

    model = model_loader(model_path)
    predictor = VehicleRiskPredictor(model)
    state = load_active_map_state(paths=settings.paths)
    profile = state.to_profile(settings.paths)
    lifecycle = lifecycle_factory(settings.carla)
    monitor: CarlaBehaviorMonitor | None = None
    try:
        lifecycle.start_server_if_configured()
        lifecycle.wait_until_ready()
        client = lifecycle.connect()
        world = client.get_world()
        standalone = not _world_matches_profile(world, profile)
        if standalone:
            world = lifecycle.load_open_drive_world(profile.xodr_path)
        _center_spectator(world, lifecycle.carla)
        traffic_manager = client.get_trafficmanager(settings.carla.traffic_manager_port)
        monitor = CarlaBehaviorMonitor(
            world=world,
            carla_module=lifecycle.carla,
            traffic_manager=traffic_manager,
            predictor=predictor,
            traffic_manager_port=settings.carla.traffic_manager_port,
            scenario_name=profile.name,
            stats_path=stats_path,
            standalone=standalone,
            random_source=random_source,
            monotonic_clock=monotonic_clock,
            wall_clock=wall_clock,
            performance_clock=performance_clock,
        )
        try:
            monitor.run(stop_requested=stop_requested)
        except KeyboardInterrupt:
            logger.info("CARLA behavior monitoring stopped by the operator")
        return 0
    finally:
        if monitor is not None:
            monitor.close()
        lifecycle.close()


def _world_matches_profile(world: Any, profile: MapProfile) -> bool:
    map_name = str(world.get_map().name).lower()
    return "opendrive" in map_name or profile.name.lower() in map_name


def _center_spectator(world: Any, carla_module: ModuleType) -> None:
    spawn_points = list(world.get_map().get_spawn_points())
    if not spawn_points:
        return
    center_x = sum(float(point.location.x) for point in spawn_points) / len(spawn_points)
    center_y = sum(float(point.location.y) for point in spawn_points) / len(spawn_points)
    world.get_spectator().set_transform(
        carla_module.Transform(
            carla_module.Location(
                x=center_x,
                y=center_y,
                z=SPECTATOR_HEIGHT_METERS,
            ),
            carla_module.Rotation(pitch=-90.0, yaw=0.0, roll=0.0),
        )
    )
