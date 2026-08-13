"""CARLA vehicle ownership, spawning and population synchronization."""

from __future__ import annotations

import random
from collections.abc import Sequence
from types import ModuleType
from typing import Any

from traffic_mirror.domain.geography import Point2D
from traffic_mirror.ports.simulator import PopulationTarget, SegmentCoverage

from .traffic_manager import (
    WAYPOINT_PROBE_HEIGHT_METERS,
    CarlaTrafficManagerCommander,
    RoadPathPinner,
)

POPULATION_HYSTERESIS_BUFFER = 10
MAXIMUM_SPAWNS_PER_TICK = 40
MINIMUM_SPAWN_GAP_METERS = 5.0
SPAWN_HEIGHT_OFFSET_METERS = 0.5
ROAD_WALK_STEP_METERS = 12.0
ROAD_WALK_MAX_DISTANCE_METERS = 60.0
HERE_COVERAGE_RADIUS_METERS = 30.0
SPAWN_INSIDE_HERE_COVERAGE_ONLY = True
SEGMENT_ASSIGNMENT_RADIUS_METERS = 50.0


class OwnedVehicleRegistry:
    """The authoritative set of actors created by this UC-01 session."""

    def __init__(self) -> None:
        self._actors: dict[int, Any] = {}

    def register(self, actor: Any) -> None:
        self._actors[actor.id] = actor

    def forget(self, actor_id: int) -> None:
        self._actors.pop(actor_id, None)

    def owns(self, actor: Any) -> bool:
        return actor.id in self._actors

    def live(self) -> list[Any]:
        dead_ids = [actor_id for actor_id, actor in self._actors.items() if not actor.is_alive]
        for actor_id in dead_ids:
            self._actors.pop(actor_id, None)
        return [actor for actor in self._actors.values() if actor.is_alive]

    def ids(self) -> set[int]:
        return {actor.id for actor in self.live()}


class SpawnPointFactory:
    def __init__(self, world: Any, carla_module: ModuleType) -> None:
        self._carla_map = world.get_map()
        self._carla = carla_module

    def _spawn_transform_from(self, waypoint: Any) -> Any:
        lane_center = waypoint.transform.location
        return self._carla.Transform(
            self._carla.Location(
                x=lane_center.x,
                y=lane_center.y,
                z=lane_center.z + SPAWN_HEIGHT_OFFSET_METERS,
            ),
            waypoint.transform.rotation,
        )

    def _lane_waypoint_at(self, point_xy: Point2D) -> Any | None:
        probe = self._carla.Location(x=point_xy[0], y=point_xy[1], z=WAYPOINT_PROBE_HEIGHT_METERS)
        return self._carla_map.get_waypoint(probe, project_to_road=True)

    def project_onto_lanes(self, points_xy: Sequence[Point2D]) -> list[Any]:
        transforms: list[Any] = []
        for point_xy in points_xy:
            waypoint = self._lane_waypoint_at(point_xy)
            if waypoint is not None:
                transforms.append(self._spawn_transform_from(waypoint))
        return transforms

    def _walk_lane(self, start_waypoint: Any, walk_forward: bool) -> list[Any]:
        transforms: list[Any] = []
        current_waypoint = start_waypoint
        walked_meters = 0.0
        while walked_meters < ROAD_WALK_MAX_DISTANCE_METERS:
            continuations = (
                current_waypoint.next(ROAD_WALK_STEP_METERS)
                if walk_forward
                else current_waypoint.previous(ROAD_WALK_STEP_METERS)
            )
            if not continuations:
                break
            current_waypoint = continuations[0]
            walked_meters += ROAD_WALK_STEP_METERS
            transforms.append(self._spawn_transform_from(current_waypoint))
        return transforms

    def densify_along_lanes(self, seed_transforms: Sequence[Any]) -> list[Any]:
        densified = list(seed_transforms)
        for seed_transform in seed_transforms:
            waypoint = self._lane_waypoint_at(
                (seed_transform.location.x, seed_transform.location.y)
            )
            if waypoint is None:
                continue
            densified.extend(self._walk_lane(waypoint, True))
            densified.extend(self._walk_lane(waypoint, False))
        return densified

    @staticmethod
    def spaced_out(transforms: Sequence[Any]) -> list[Any]:
        kept: list[Any] = []
        for transform in transforms:
            if all(
                transform.location.distance(existing.location) >= MINIMUM_SPAWN_GAP_METERS
                for existing in kept
            ):
                kept.append(transform)
        return kept

    def candidates_along(self, points_xy: Sequence[Point2D]) -> list[Any]:
        seeds = self.project_onto_lanes(points_xy)
        return self.spaced_out(self.densify_along_lanes(seeds))


def nearest_coverage(
    location: Any, coverages: Sequence[SegmentCoverage]
) -> tuple[int | None, float]:
    nearest_index: int | None = None
    nearest_distance = float("inf")
    for index, coverage in enumerate(coverages):
        if not coverage.points_xy:
            continue
        distance = coverage.distance_from((location.x, location.y))
        if distance < nearest_distance:
            nearest_index = index
            nearest_distance = distance
    return nearest_index, nearest_distance


def vehicle_counts_by_coverage(
    vehicles: Sequence[Any], coverages: Sequence[SegmentCoverage]
) -> dict[int, int]:
    counts = {index: 0 for index in range(len(coverages))}
    for vehicle in vehicles:
        index, distance = nearest_coverage(vehicle.get_location(), coverages)
        if index is not None and distance <= SEGMENT_ASSIGNMENT_RADIUS_METERS:
            counts[index] += 1
    return counts


class CarlaPopulationManager:
    def __init__(
        self,
        *,
        client: Any,
        world: Any,
        carla_module: ModuleType,
        traffic_manager_port: int,
        commander: CarlaTrafficManagerCommander,
        path_pinner: RoadPathPinner,
        registry: OwnedVehicleRegistry,
        random_source: random.Random | None = None,
    ) -> None:
        self._client = client
        self._world = world
        self._carla = carla_module
        self._traffic_manager_port = traffic_manager_port
        self._commander = commander
        self._path_pinner = path_pinner
        self.registry = registry
        self._random = random_source or random.Random()
        self._vehicle_blueprints = list(world.get_blueprint_library().filter("vehicle.*"))
        self._spawn_points = list(world.get_map().get_spawn_points())
        self._spawn_factory = SpawnPointFactory(world, carla_module)

    def active_vehicles(self) -> list[Any]:
        return self.registry.live()

    def _all_world_vehicle_locations(self) -> list[Any]:
        return [
            actor.get_location()
            for actor in self._world.get_actors().filter("vehicle.*")
            if actor.is_alive
        ]

    @staticmethod
    def _transforms_clear_of_traffic(
        transforms: Sequence[Any], occupied_locations: Sequence[Any]
    ) -> list[Any]:
        return [
            transform
            for transform in transforms
            if all(
                occupied.distance(transform.location) >= MINIMUM_SPAWN_GAP_METERS
                for occupied in occupied_locations
            )
        ]

    def _spawn_at(self, transform: Any) -> Any | None:
        if not self._vehicle_blueprints:
            return None
        vehicle = self._world.try_spawn_actor(
            self._random.choice(self._vehicle_blueprints), transform
        )
        if vehicle is None:
            return None
        self.registry.register(vehicle)
        try:
            vehicle.set_autopilot(True, self._traffic_manager_port)
            self._commander.configure_new_vehicle(vehicle)
        except Exception:
            self.destroy([vehicle])
            raise
        return vehicle

    def destroy(self, vehicles: Sequence[Any]) -> int:
        # Intentional correction: only actors registered by this manager may be
        # destroyed.  External ScenarioRunner/user actors remain untouched.
        doomed = [
            vehicle for vehicle in vehicles if self.registry.owns(vehicle) and vehicle.is_alive
        ]
        if not doomed:
            return 0
        for vehicle in doomed:
            self._commander.disable_autopilot(vehicle)
        self._client.apply_batch_sync(
            [self._carla.command.DestroyActor(vehicle.id) for vehicle in doomed],
            True,
        )
        for vehicle in doomed:
            self.registry.forget(vehicle.id)
        return len(doomed)

    def cull_excess(
        self,
        vehicles: Sequence[Any],
        target_count: int,
        coverages: Sequence[SegmentCoverage] = (),
    ) -> int:
        excess_count = len(vehicles) - target_count
        if excess_count <= 0:
            return 0
        ordered = list(vehicles)
        usable = [coverage for coverage in coverages if coverage.points_xy]
        if usable:
            ordered.sort(
                key=lambda vehicle: min(
                    coverage.distance_from((vehicle.get_location().x, vehicle.get_location().y))
                    for coverage in usable
                ),
                reverse=True,
            )
        return self.destroy(ordered[:excess_count])

    def synchronize_population(self, targets: Sequence[PopulationTarget]) -> int:
        target_list = list(targets)
        coverages = [target.coverage for target in target_list]
        vehicles = self.active_vehicles()
        total_target = sum(target.target_count for target in target_list)
        if len(vehicles) > total_target + POPULATION_HYSTERESIS_BUFFER:
            self.cull_excess(vehicles, total_target, coverages)
            return total_target

        full_deficit = total_target - len(vehicles)
        if full_deficit <= 0:
            return total_target
        spawn_budget = min(full_deficit, MAXIMUM_SPAWNS_PER_TICK)
        current_counts = vehicle_counts_by_coverage(vehicles, coverages)
        occupied_locations = self._all_world_vehicle_locations()
        busiest_first = sorted(
            range(len(target_list)),
            key=lambda index: target_list[index].coverage.segment.jam_factor,
            reverse=True,
        )
        for index in busiest_first:
            if spawn_budget <= 0:
                break
            target = target_list[index]
            if not target.coverage.points_xy:
                continue
            deficit = min(
                target.target_count - current_counts.get(index, 0),
                spawn_budget,
            )
            if deficit <= 0:
                continue
            candidates = self._transforms_clear_of_traffic(
                self._spawn_factory.candidates_along(target.coverage.points_xy),
                occupied_locations,
            )
            self._random.shuffle(candidates)
            spawned = 0
            for candidate in candidates:
                if spawned >= deficit:
                    break
                vehicle = self._spawn_at(candidate)
                if vehicle is None:
                    continue
                self._path_pinner.pin(vehicle, target.coverage.points_xy)
                occupied_locations.append(vehicle.get_location())
                spawned += 1
            spawn_budget -= spawned
        return total_target

    def synchronize_uniform_population(
        self, target_count: int, coverage_anchor_points: Sequence[Point2D]
    ) -> int:
        vehicles = self.active_vehicles()
        if len(vehicles) > target_count + POPULATION_HYSTERESIS_BUFFER:
            self.cull_excess(vehicles, target_count)
            return target_count
        full_deficit = target_count - len(vehicles)
        if full_deficit <= 0:
            return target_count

        occupied = self._all_world_vehicle_locations()
        candidates = self._uniform_candidates(self._spawn_points, coverage_anchor_points, occupied)
        spawn_budget = min(full_deficit, MAXIMUM_SPAWNS_PER_TICK)
        spawned = 0
        for candidate in candidates:
            if spawned >= spawn_budget:
                break
            if self._spawn_at(candidate) is not None:
                spawned += 1
        return target_count

    def _uniform_candidates(
        self,
        automatic_spawn_points: Sequence[Any],
        anchor_points: Sequence[Point2D],
        occupied_locations: Sequence[Any],
    ) -> list[Any]:
        free_automatic = self._transforms_clear_of_traffic(
            automatic_spawn_points, occupied_locations
        )
        if not (SPAWN_INSIDE_HERE_COVERAGE_ONLY and anchor_points):
            self._random.shuffle(free_automatic)
            return free_automatic
        automatic_in_coverage = [
            transform
            for transform in free_automatic
            if min(
                (
                    (
                        (transform.location.x - anchor_x) ** 2
                        + (transform.location.y - anchor_y) ** 2
                    )
                    ** 0.5
                    for anchor_x, anchor_y in anchor_points
                ),
                default=float("inf"),
            )
            <= HERE_COVERAGE_RADIUS_METERS
        ]
        projected = self._spawn_factory.project_onto_lanes(anchor_points)
        densified = self._spawn_factory.densify_along_lanes(projected)
        combined = self._spawn_factory.spaced_out(automatic_in_coverage + densified)
        self._random.shuffle(combined)
        return combined
