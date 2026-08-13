"""Owned-fleet sanitation rules for CARLA."""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any

from traffic_mirror.domain.geography import planar_distance_meters
from traffic_mirror.ports.simulator import SegmentCoverage

from .population import CarlaPopulationManager, OwnedVehicleRegistry

FALL_THROUGH_HEIGHT_METERS = -0.5
STOPPED_SPEED_THRESHOLD_METERS_PER_SECOND = 0.5
FROZEN_TIMEOUT_SECONDS = 60.0
OFF_ROAD_TILT_DEGREES = 10.0
OFF_ROAD_LANE_DISTANCE_METERS = 2.0
OFF_ROAD_GRACE_SECONDS = 3.0
STRAY_MAX_DISTANCE_METERS = 60.0


def vehicle_speed_meters_per_second(vehicle: Any) -> float:
    velocity = vehicle.get_velocity()
    return math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)


class VehicleRemovalRule(ABC):
    skips_vehicles_held_at_closure = True

    def before_scan(self, world: Any) -> None:
        del world

    @abstractmethod
    def should_remove(self, vehicle: Any) -> bool: ...

    def after_removal(self, vehicle: Any) -> None:
        del vehicle

    def forget_missing(self, live_vehicle_ids: set[int]) -> None:
        del live_vehicle_ids


class FellThroughMapRule(VehicleRemovalRule):
    skips_vehicles_held_at_closure = False

    def should_remove(self, vehicle: Any) -> bool:
        return bool(vehicle.get_location().z < FALL_THROUGH_HEIGHT_METERS)


class FrozenInTrafficRule(VehicleRemovalRule):
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._stopped_since: dict[int, float] = {}

    def should_remove(self, vehicle: Any) -> bool:
        now = self._clock()
        if vehicle_speed_meters_per_second(vehicle) >= STOPPED_SPEED_THRESHOLD_METERS_PER_SECOND:
            self._stopped_since.pop(vehicle.id, None)
            return False
        first_stopped_at = self._stopped_since.setdefault(vehicle.id, now)
        return now - first_stopped_at > FROZEN_TIMEOUT_SECONDS

    def after_removal(self, vehicle: Any) -> None:
        self._stopped_since.pop(vehicle.id, None)

    def forget_missing(self, live_vehicle_ids: set[int]) -> None:
        self._stopped_since = {
            vehicle_id: stopped_at
            for vehicle_id, stopped_at in self._stopped_since.items()
            if vehicle_id in live_vehicle_ids
        }


class TiltedOffRoadRule(VehicleRemovalRule):
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._off_road_since: dict[int, float] = {}
        self._carla_map: Any | None = None

    def before_scan(self, world: Any) -> None:
        self._carla_map = world.get_map()

    def should_remove(self, vehicle: Any) -> bool:
        now = self._clock()
        is_stopped = (
            vehicle_speed_meters_per_second(vehicle) < STOPPED_SPEED_THRESHOLD_METERS_PER_SECOND
        )
        if not (is_stopped and self._is_off_road(vehicle)):
            self._off_road_since.pop(vehicle.id, None)
            return False
        first_seen = self._off_road_since.setdefault(vehicle.id, now)
        return now - first_seen > OFF_ROAD_GRACE_SECONDS

    def _is_off_road(self, vehicle: Any) -> bool:
        if self._carla_map is None:
            return False
        transform = vehicle.get_transform()
        if (
            abs(transform.rotation.roll) > OFF_ROAD_TILT_DEGREES
            or abs(transform.rotation.pitch) > OFF_ROAD_TILT_DEGREES
        ):
            return True
        waypoint = self._carla_map.get_waypoint(transform.location, project_to_road=True)
        if waypoint is None:
            return True
        lane_center = waypoint.transform.location
        return (
            planar_distance_meters(
                transform.location.x,
                transform.location.y,
                lane_center.x,
                lane_center.y,
            )
            > OFF_ROAD_LANE_DISTANCE_METERS
        )

    def after_removal(self, vehicle: Any) -> None:
        self._off_road_since.pop(vehicle.id, None)

    def forget_missing(self, live_vehicle_ids: set[int]) -> None:
        self._off_road_since = {
            vehicle_id: started_at
            for vehicle_id, started_at in self._off_road_since.items()
            if vehicle_id in live_vehicle_ids
        }


class OutsideCoverageRule(VehicleRemovalRule):
    def __init__(self) -> None:
        self._coverages: tuple[SegmentCoverage, ...] = ()

    def set_coverage(self, coverages: Sequence[SegmentCoverage]) -> None:
        self._coverages = tuple(coverage for coverage in coverages if coverage.points_xy)

    def should_remove(self, vehicle: Any) -> bool:
        if not self._coverages:
            return False
        location = vehicle.get_location()
        return (
            min(coverage.distance_from((location.x, location.y)) for coverage in self._coverages)
            > STRAY_MAX_DISTANCE_METERS
        )


class FleetSanitizer:
    def __init__(
        self,
        *,
        world: Any,
        population_manager: CarlaPopulationManager,
        registry: OwnedVehicleRegistry,
        rules: Sequence[VehicleRemovalRule],
    ) -> None:
        self._world = world
        self._population_manager = population_manager
        self._registry = registry
        self._rules = tuple(rules)

    def run(self, vehicle_ids_held_at_closure: set[int]) -> int:
        total_removed = 0
        for rule in self._rules:
            rule.before_scan(self._world)
            doomed = [
                vehicle
                for vehicle in self._registry.live()
                if not (
                    rule.skips_vehicles_held_at_closure
                    and vehicle.id in vehicle_ids_held_at_closure
                )
                and rule.should_remove(vehicle)
            ]
            removed = self._population_manager.destroy(doomed)
            for vehicle in doomed:
                rule.after_removal(vehicle)
            total_removed += removed
        self.forget_missing()
        return total_removed

    def forget_missing(self) -> None:
        live_ids = self._registry.ids()
        for rule in self._rules:
            rule.forget_missing(live_ids)
