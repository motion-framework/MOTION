"""CARLA implementation of the UC-01 simulator port."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any

from motion.config.settings import CarlaSettings
from motion.domain.geography import Point2D
from motion.domain.maps import MapProfile
from motion.domain.mirroring import (
    DEFAULT_FALLBACK_SLOWDOWN_PERCENTAGE,
    DrivingCommand,
)
from motion.ports.simulator import (
    PopulationTarget,
    SegmentCommand,
    SegmentCoverage,
)

from .lifecycle import CarlaLifecycle
from .population import (
    CarlaPopulationManager,
    OwnedVehicleRegistry,
    nearest_coverage,
)
from .sanitizer import (
    FellThroughMapRule,
    FleetSanitizer,
    FrozenInTrafficRule,
    OutsideCoverageRule,
    TiltedOffRoadRule,
)
from .traffic_manager import CarlaTrafficManagerCommander, RoadPathPinner

GLOBAL_FOLLOW_DISTANCE_METERS = 3.0
SPECTATOR_HEIGHT_METERS = 120.0


class CarlaTrafficSimulator:
    """CARLA facade with explicit actor ownership and deterministic cleanup."""

    def __init__(
        self,
        *,
        client: Any,
        world: Any,
        traffic_manager: Any,
        carla_module: ModuleType,
        traffic_manager_port: int,
        speed_limit_kmh: float,
        lifecycle: CarlaLifecycle | None = None,
        close_lifecycle: bool = False,
        random_source: random.Random | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._world = world
        self._traffic_manager = traffic_manager
        self._carla = carla_module
        self._lifecycle = lifecycle
        self._close_lifecycle = close_lifecycle
        self._closed = False
        self._held_at_closure: set[int] = set()

        self._configure_traffic_manager()
        self._commander = CarlaTrafficManagerCommander(
            traffic_manager,
            carla_module,
            traffic_manager_port=traffic_manager_port,
            speed_limit_kmh=speed_limit_kmh,
        )
        self._path_pinner = RoadPathPinner(self._commander)
        self._registry = OwnedVehicleRegistry()
        self._population = CarlaPopulationManager(
            client=client,
            world=world,
            carla_module=carla_module,
            traffic_manager_port=traffic_manager_port,
            commander=self._commander,
            path_pinner=self._path_pinner,
            registry=self._registry,
            random_source=random_source,
        )
        self._outside_coverage = OutsideCoverageRule()
        fell_through = FellThroughMapRule()
        self._tick_sanitizer = FleetSanitizer(
            world=world,
            population_manager=self._population,
            registry=self._registry,
            rules=(
                self._outside_coverage,
                fell_through,
                FrozenInTrafficRule(monotonic_clock),
            ),
        )
        self._watchdog_sanitizer = FleetSanitizer(
            world=world,
            population_manager=self._population,
            registry=self._registry,
            rules=(TiltedOffRoadRule(monotonic_clock), fell_through),
        )

    @classmethod
    def from_profile(
        cls,
        settings: CarlaSettings,
        profile: MapProfile,
        *,
        lifecycle: CarlaLifecycle | None = None,
        start_server: bool = True,
        random_source: random.Random | None = None,
    ) -> CarlaTrafficSimulator:
        session = lifecycle or CarlaLifecycle(settings)
        owns_lifecycle = lifecycle is None
        try:
            if start_server:
                session.start_server_if_configured()
            session.wait_until_ready()
            client = session.connect()
            world = session.load_open_drive_world(profile.xodr_path)
            manager = session.traffic_manager()
            return cls(
                client=client,
                world=world,
                traffic_manager=manager,
                carla_module=session.carla,
                traffic_manager_port=settings.traffic_manager_port,
                speed_limit_kmh=profile.speed_limit_kmh,
                lifecycle=session,
                close_lifecycle=owns_lifecycle,
                random_source=random_source,
            )
        except Exception:
            if owns_lifecycle:
                session.close()
            raise

    @property
    def owned_vehicle_ids(self) -> frozenset[int]:
        return frozenset(self._registry.ids())

    @property
    def world(self) -> Any:
        """Expose the loaded world to CARLA-specific diagnostic adapters."""

        return self._world

    @property
    def carla_module(self) -> ModuleType:
        return self._carla

    def _configure_traffic_manager(self) -> None:
        self._traffic_manager.set_synchronous_mode(False)
        self._traffic_manager.set_global_distance_to_leading_vehicle(GLOBAL_FOLLOW_DISTANCE_METERS)
        self._traffic_manager.global_percentage_speed_difference(
            DEFAULT_FALLBACK_SLOWDOWN_PERCENTAGE
        )

    def owned_vehicle_count(self) -> int:
        return len(self._registry.live())

    def synchronize_population(self, targets: Sequence[PopulationTarget]) -> int:
        return self._population.synchronize_population(targets)

    def synchronize_uniform_population(
        self, target_count: int, coverage_anchor_points: Sequence[Point2D]
    ) -> int:
        return self._population.synchronize_uniform_population(target_count, coverage_anchor_points)

    def apply_segment_commands(
        self,
        commands: Sequence[SegmentCommand],
        fallback_command: DrivingCommand,
    ) -> int:
        usable = [command for command in commands if command.coverage.points_xy]
        commanded_count = 0
        for vehicle in self._registry.live():
            if usable:
                index, _distance = nearest_coverage(
                    vehicle.get_location(),
                    [command.coverage for command in usable],
                )
                selected = usable[index].command if index is not None else fallback_command
            else:
                selected = fallback_command
            if not self._commander.apply(vehicle, selected):
                continue
            if selected.is_held_at_closure:
                self._held_at_closure.add(vehicle.id)
            else:
                self._held_at_closure.discard(vehicle.id)
            commanded_count += 1
        self._held_at_closure.intersection_update(self._registry.ids())
        return commanded_count

    def repin_to_road(self, coverages: Sequence[SegmentCoverage]) -> int:
        usable = [coverage for coverage in coverages if len(coverage.points_xy) >= 2]
        if not usable:
            return 0
        repinned = 0
        for vehicle in self._registry.live():
            if vehicle.id in self._held_at_closure:
                continue
            index, _distance = nearest_coverage(vehicle.get_location(), usable)
            if index is not None and self._path_pinner.pin(vehicle, usable[index].points_xy):
                repinned += 1
        return repinned

    def set_mirrored_coverage(self, coverages: Sequence[SegmentCoverage]) -> None:
        self._outside_coverage.set_coverage(coverages)

    def sanitize_tick(self) -> int:
        removed = self._tick_sanitizer.run(self._held_at_closure)
        self._forget_removed()
        return removed

    def sanitize_watchdog(self) -> int:
        removed = self._watchdog_sanitizer.run(self._held_at_closure)
        self._forget_removed()
        return removed

    def _forget_removed(self) -> None:
        live_ids = self._registry.ids()
        self._held_at_closure.intersection_update(live_ids)
        self._tick_sanitizer.forget_missing()
        self._watchdog_sanitizer.forget_missing()

    def focus_view(self, anchor_points: Sequence[Point2D]) -> None:
        if not anchor_points:
            return
        center_x = sum(point[0] for point in anchor_points) / len(anchor_points)
        center_y = sum(point[1] for point in anchor_points) / len(anchor_points)
        self._world.get_spectator().set_transform(
            self._carla.Transform(
                self._carla.Location(x=center_x, y=center_y, z=SPECTATOR_HEIGHT_METERS),
                self._carla.Rotation(pitch=-90),
            )
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._population.destroy(self._registry.live())
        finally:
            self._held_at_closure.clear()
            if self._close_lifecycle and self._lifecycle is not None:
                self._lifecycle.close()

    def __enter__(self) -> CarlaTrafficSimulator:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()
