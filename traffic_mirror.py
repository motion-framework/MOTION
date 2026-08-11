from __future__ import annotations

import math
import os
import random
import time
import carla
import init_main_map as main_map_tool

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from device_traffic_feed import (
    DEVICE_REGISTRY,
    DeviceReading,
    get_device_coordinates,
    poll_all_devices,
)
from geo_transform import build_geo_transform
from here_traffic import TrafficSegment, TrafficService
from map_profile import get_active_profile
from segment_population import derive_population_targets


CARLA_HOST = "localhost"
CARLA_PORT = 2000
CARLA_CLIENT_TIMEOUT_SECONDS = 15.0
TRAFFIC_MANAGER_PORT = 8000

UPDATE_INTERVAL_SECONDS = 60.0
WATCHDOG_INTERVAL_SECONDS = 1.0

MINIMUM_VEHICLE_COUNT = 20
MAXIMUM_VEHICLE_COUNT = 80
DEVICE_COUNT_TO_SIMULATION_SCALE = 5
POPULATION_HYSTERESIS_BUFFER = 10
MAXIMUM_SPAWNS_PER_TICK = 40

GLOBAL_FOLLOW_DISTANCE_METERS = 3.0
NORMAL_FOLLOW_DISTANCE_METERS = 2.0
INCIDENT_FOLLOW_DISTANCE_METERS = 8.0

DEFAULT_FALLBACK_SLOWDOWN_PERCENTAGE = 20.0
MAXIMUM_SLOWDOWN_PERCENTAGE = 85.0
CLOSED_ROAD_SLOWDOWN_PERCENTAGE = 100.0
JAM_FACTOR_AGGRESSION_THRESHOLD = 3.0
JAM_IGNORE_VEHICLES_PERCENTAGE = 5

MINIMUM_SPAWN_GAP_METERS = 5.0
SPAWN_HEIGHT_OFFSET_METERS = 0.5
WAYPOINT_PROBE_HEIGHT_METERS = 0.5
ROAD_WALK_STEP_METERS = 12.0
ROAD_WALK_MAX_DISTANCE_METERS = 60.0
HERE_COVERAGE_RADIUS_METERS = 30.0
SPAWN_INSIDE_HERE_COVERAGE_ONLY = True

SEGMENT_ASSIGNMENT_RADIUS_METERS = 50.0
STRAY_MAX_DISTANCE_METERS = 60.0
FALL_THROUGH_HEIGHT_METERS = -0.5
STOPPED_SPEED_THRESHOLD_METERS_PER_SECOND = 0.5
FROZEN_TIMEOUT_SECONDS = 60.0
OFF_ROAD_TILT_DEGREES = 10.0
OFF_ROAD_LANE_DISTANCE_METERS = 2.0
OFF_ROAD_GRACE_SECONDS = 3.0

GEO_SEGMENT_FILTER_RADIUS_METERS = 150.0
FUNCTIONAL_CLASS_TOLERANCE = 1

GEO_FILTER_ENVIRONMENT_VARIABLE = "MIRROR_GEO_FILTER"
ANCHOR_FUNCTIONAL_CLASS_ENV = "MIRROR_ANCHOR_FC"

DEFAULT_SEGMENT_LENGTH_METERS = 100.0
SPECTATOR_HEIGHT_METERS = 120.0
DESCRIPTION_PRINT_WIDTH = 35
ROAD_FILTER_ENVIRONMENT_VARIABLE = "MIRROR_ROAD_FILTER"
LOG_PREFIX = "[traffic_mirror]"


def planar_distance_meters(
    first_x: float, first_y: float, second_x: float, second_y: float
) -> float:
    return math.hypot(first_x - second_x, first_y - second_y)


def distance_point_to_line_segment(
    point_x: float,
    point_y: float,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> float:
    edge_x = end_x - start_x
    edge_y = end_y - start_y
    edge_length_squared = edge_x * edge_x + edge_y * edge_y
    if edge_length_squared == 0.0:
        return planar_distance_meters(point_x, point_y, start_x, start_y)
    projection_ratio = (
        (point_x - start_x) * edge_x + (point_y - start_y) * edge_y
    ) / edge_length_squared
    ratio_inside_segment = max(0.0, min(1.0, projection_ratio))
    closest_x = start_x + ratio_inside_segment * edge_x
    closest_y = start_y + ratio_inside_segment * edge_y
    return planar_distance_meters(point_x, point_y, closest_x, closest_y)


def distance_point_to_polyline(
    point_x: float, point_y: float, polyline_points: list[tuple[float, float]]
) -> float:
    if not polyline_points:
        return float("inf")
    if len(polyline_points) == 1:
        return planar_distance_meters(
            point_x, point_y, polyline_points[0][0], polyline_points[0][1]
        )
    return min(
        distance_point_to_line_segment(point_x, point_y, start_x, start_y, end_x, end_y)
        for (start_x, start_y), (end_x, end_y) in zip(polyline_points, polyline_points[1:])
    )


def polyline_length_meters(polyline_points: list[tuple[float, float]]) -> float:
    return sum(
        planar_distance_meters(start_x, start_y, end_x, end_y)
        for (start_x, start_y), (end_x, end_y) in zip(polyline_points, polyline_points[1:])
    )


def vehicle_speed_meters_per_second(vehicle: carla.Actor) -> float:
    velocity = vehicle.get_velocity()
    return math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)


def live_vehicles(world: carla.World) -> list[carla.Actor]:
    return [actor for actor in world.get_actors().filter("vehicle.*") if actor.is_alive]


def road_filter_from_environment() -> str:
    return os.environ.get(ROAD_FILTER_ENVIRONMENT_VARIABLE, "")


def geo_filter_enabled() -> bool:
    return os.environ.get(GEO_FILTER_ENVIRONMENT_VARIABLE, "") == "1"


def derive_target_vehicle_count(readings: list[DeviceReading]) -> int:
    if not readings:
        return MINIMUM_VEHICLE_COUNT
    average_observed_count = sum(reading.count for reading in readings) / len(readings)
    scaled_count = int(average_observed_count * DEVICE_COUNT_TO_SIMULATION_SCALE)
    return max(MINIMUM_VEHICLE_COUNT, min(MAXIMUM_VEHICLE_COUNT, scaled_count))


class GeographicProjector:
    def __init__(self, open_street_map_path: str, map_projection_string: str) -> None:
        self._geo_transform = build_geo_transform(open_street_map_path, map_projection_string)

    def to_carla_xy(self, latitude: float, longitude: float) -> tuple[float, float]:
        return self._geo_transform.to_carla(latitude, longitude)


ACTIVE_MAP_PROFILE = get_active_profile()
GEOGRAPHIC_PROJECTOR = GeographicProjector(ACTIVE_MAP_PROFILE.osm_path, ACTIVE_MAP_PROFILE.proj_string)

def geo_to_carla(latitude: float, longitude: float) -> tuple[float, float]:
    return GEOGRAPHIC_PROJECTOR.to_carla_xy(latitude, longitude)


@dataclass(frozen=True)
class SegmentPolyline:
    segment: TrafficSegment
    carla_points: list[tuple[float, float]]

    def distance_from(self, location: carla.Location) -> float:
        return distance_point_to_polyline(location.x, location.y, self.carla_points)


def distance_from_coverage(
    location: carla.Location, polylines: list[SegmentPolyline]
) -> float:
    return min(
        (polyline.distance_from(location) for polyline in polylines if polyline.carla_points),
        default=0.0,
    )


def nearest_polyline_index(
    location: carla.Location, polylines: list[SegmentPolyline]
) -> tuple[int | None, float]:
    nearest_index: int | None = None
    nearest_distance = float("inf")
    for index, polyline in enumerate(polylines):
        if not polyline.carla_points:
            continue
        distance = polyline.distance_from(location)
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_index = index
    return nearest_index, nearest_distance


def vehicle_counts_by_polyline(
    vehicles: list[carla.Actor], polylines: list[SegmentPolyline]
) -> dict[int, int]:
    counts = {index: 0 for index in range(len(polylines))}
    for vehicle in vehicles:
        index, distance = nearest_polyline_index(vehicle.get_location(), polylines)
        if index is not None and distance <= SEGMENT_ASSIGNMENT_RADIUS_METERS:
            counts[index] += 1
    return counts


class MapCoverage:
    def __init__(self, map_profile, projector: GeographicProjector) -> None:
        self._bounding_box = map_profile.bbox
        self._projector = projector

    def contains(self, latitude: float, longitude: float) -> bool:
        box = self._bounding_box
        return (
            box.south_west_lat <= latitude <= box.north_east_lat
            and box.south_west_lon <= longitude <= box.north_east_lon
        )

    @staticmethod
    def geographic_points_of(segment: TrafficSegment) -> list[tuple[float, float]]:
        return list(segment.shape_points) or [(segment.lat, segment.lon)]

    def segments_touching_map(
        self, segments: list[TrafficSegment]
    ) -> list[TrafficSegment]:
        return [
            segment
            for segment in segments
            if any(
                self.contains(latitude, longitude)
                for latitude, longitude in self.geographic_points_of(segment)
            )
        ]

    def polyline_of(self, segment: TrafficSegment) -> SegmentPolyline:
        points_inside_map = [
            (latitude, longitude)
            for latitude, longitude in self.geographic_points_of(segment)
            if self.contains(latitude, longitude)
        ]
        return SegmentPolyline(
            segment=segment,
            carla_points=[
                self._projector.to_carla_xy(latitude, longitude)
                for latitude, longitude in points_inside_map
            ],
        )

    def polylines_of(self, segments: list[TrafficSegment]) -> list[SegmentPolyline]:
        return [self.polyline_of(segment) for segment in segments]

    def segments_resized_to_map(
        self, polylines: list[SegmentPolyline]
    ) -> list[TrafficSegment]:
        resized_segments: list[TrafficSegment] = []
        for polyline in polylines:
            length_inside_map = (
                polyline_length_meters(polyline.carla_points) or DEFAULT_SEGMENT_LENGTH_METERS
            )
            print(
                f"{LOG_PREFIX} {polyline.segment.description[:DESCRIPTION_PRINT_WIDTH]}: "
                f"{length_inside_map:.0f} m inside the map "
                f"(HERE reports {polyline.segment.length_m:.0f} m for the whole road)."
            )
            resized_segments.append(replace(polyline.segment, length_m=length_inside_map))
        return resized_segments


@dataclass(frozen=True)
class DrivingCommand:
    slowdown_percentage: float
    target_speed_kmh: float 
    follow_distance_meters: float
    ignore_vehicles_percentage: int
    is_held_at_closure: bool


class SpeedMirrorPolicy:
    def __init__(
        self,
        speed_limit_kmh: float,
        fallback_slowdown_percentage: float = DEFAULT_FALLBACK_SLOWDOWN_PERCENTAGE,
    ) -> None:
        self._speed_limit_kmh = speed_limit_kmh
        self._fallback_slowdown_percentage = fallback_slowdown_percentage

    def target_speed_for(self, segment: TrafficSegment) -> float:
        segment_cap = segment.free_kmh if segment.free_kmh > 0.0 else self._speed_limit_kmh
        return max(0.0, min(segment.speed_kmh, segment_cap))

    def slowdown_percentage_for(self, segment: TrafficSegment) -> float:
        reference_speed = segment.free_kmh if segment.free_kmh > 0.0 else self._speed_limit_kmh
        if reference_speed <= 0.0:
            return self._fallback_slowdown_percentage
        achievable_speed_kmh = min(segment.speed_kmh, reference_speed)
        slowdown_percentage = (
            (reference_speed - achievable_speed_kmh) / reference_speed * 100.0
        )
        return max(0.0, min(MAXIMUM_SLOWDOWN_PERCENTAGE, slowdown_percentage))

    def command_for(self, segment: TrafficSegment) -> DrivingCommand:
        if segment.road_closure:
            return DrivingCommand(
                slowdown_percentage=CLOSED_ROAD_SLOWDOWN_PERCENTAGE,
                target_speed_kmh=0.0,
                follow_distance_meters=INCIDENT_FOLLOW_DISTANCE_METERS,
                ignore_vehicles_percentage=0,
                is_held_at_closure=True,
            )
        has_incident_nearby = segment.incidents_nearby > 0
        is_moving_jam = segment.jam_factor > JAM_FACTOR_AGGRESSION_THRESHOLD
        return DrivingCommand(
            slowdown_percentage=self.slowdown_percentage_for(segment),
            target_speed_kmh=self.target_speed_for(segment),
            follow_distance_meters=(
                INCIDENT_FOLLOW_DISTANCE_METERS
                if has_incident_nearby
                else NORMAL_FOLLOW_DISTANCE_METERS
            ),
            ignore_vehicles_percentage=(
                JAM_IGNORE_VEHICLES_PERCENTAGE if is_moving_jam else 0
            ),
            is_held_at_closure=False,
        )

    def fallback_command(self) -> DrivingCommand:
        return DrivingCommand(
            slowdown_percentage=self._fallback_slowdown_percentage,
            target_speed_kmh=self._speed_limit_kmh
                * (1.0 - self._fallback_slowdown_percentage / 100.0),
            follow_distance_meters=NORMAL_FOLLOW_DISTANCE_METERS,
            ignore_vehicles_percentage=0,
            is_held_at_closure=False,
        )


class TrafficManagerCommander:
    def __init__(self, traffic_manager: carla.TrafficManager) -> None:
        self._traffic_manager = traffic_manager

    def configure_new_vehicle(self, vehicle: carla.Actor) -> None:
        self._traffic_manager.distance_to_leading_vehicle(
            vehicle, NORMAL_FOLLOW_DISTANCE_METERS
        )
        self._traffic_manager.set_desired_speed(
            vehicle,
            (100.0 - DEFAULT_FALLBACK_SLOWDOWN_PERCENTAGE) / 100.0
            * ACTIVE_MAP_PROFILE.speed_limit_kmh,
        )
        self._traffic_manager.auto_lane_change(vehicle, True)
        self._traffic_manager.ignore_walkers_percentage(vehicle, 0)
        self._traffic_manager.ignore_lights_percentage(vehicle, 0)
        self._traffic_manager.ignore_signs_percentage(vehicle, 0)

    def apply(self, vehicle: carla.Actor, command: DrivingCommand) -> bool:
        try:
            self._traffic_manager.set_desired_speed(vehicle, command.target_speed_kmh)
            self._traffic_manager.distance_to_leading_vehicle(
                vehicle, command.follow_distance_meters
            )
            self._traffic_manager.ignore_vehicles_percentage(
                vehicle, command.ignore_vehicles_percentage
            )
            return True
        except Exception as error:
            print(f"{LOG_PREFIX} Could not command vehicle {vehicle.id}: {error}")
            return False

    def follow_path(
        self, vehicle: carla.Actor, path_points: list[tuple[float, float]]
    ) -> bool:
        try:
            self._traffic_manager.set_path(
                vehicle,
                [
                    carla.Location(x=point_x, y=point_y, z=WAYPOINT_PROBE_HEIGHT_METERS)
                    for point_x, point_y in path_points
                ],
            )
            return True
        except Exception as error:
            print(f"{LOG_PREFIX} Could not pin vehicle {vehicle.id} to its road: {error}")
            return False

    def disable_autopilot(self, vehicle: carla.Actor) -> bool:
        try:
            vehicle.set_autopilot(False, TRAFFIC_MANAGER_PORT)
            return True
        except Exception:
            return False


class RoadPathPinner:
    def __init__(self, commander: TrafficManagerCommander) -> None:
        self._commander = commander

    def pin(self, vehicle: carla.Actor, polyline_points: list[tuple[float, float]]) -> bool:
        path_ahead = self._path_in_travel_direction(vehicle, polyline_points)
        if not path_ahead:
            return False
        return self._commander.follow_path(vehicle, path_ahead)

    @staticmethod
    def _path_in_travel_direction(
        vehicle: carla.Actor, polyline_points: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        if len(polyline_points) < 2:
            return []
        location = vehicle.get_location()
        nearest_index = min(
            range(len(polyline_points)),
            key=lambda index: planar_distance_meters(
                location.x, location.y, polyline_points[index][0], polyline_points[index][1]
            ),
        )
        points_ahead = polyline_points[nearest_index + 1 :]
        points_behind = list(reversed(polyline_points[:nearest_index]))
        forward_vector = vehicle.get_transform().get_forward_vector()

        def alignment_with(candidate_points: list[tuple[float, float]]) -> float:
            if not candidate_points:
                return -2.0
            delta_x = candidate_points[0][0] - location.x
            delta_y = candidate_points[0][1] - location.y
            delta_length = math.hypot(delta_x, delta_y) or 1.0
            return (delta_x * forward_vector.x + delta_y * forward_vector.y) / delta_length

        if alignment_with(points_ahead) >= alignment_with(points_behind):
            return points_ahead
        return points_behind


class SpawnPointFactory:
    def __init__(self, world: carla.World) -> None:
        self._carla_map = world.get_map()

    @staticmethod
    def _spawn_transform_from(waypoint: carla.Waypoint) -> carla.Transform:
        lane_center = waypoint.transform.location
        return carla.Transform(
            carla.Location(
                x=lane_center.x,
                y=lane_center.y,
                z=lane_center.z + SPAWN_HEIGHT_OFFSET_METERS,
            ),
            waypoint.transform.rotation,
        )

    def _lane_waypoint_at(self, carla_x: float, carla_y: float) -> carla.Waypoint | None:
        probe_location = carla.Location(
            x=carla_x, y=carla_y, z=WAYPOINT_PROBE_HEIGHT_METERS
        )
        return self._carla_map.get_waypoint(probe_location, project_to_road=True)

    def project_onto_lanes(
        self, carla_points: list[tuple[float, float]]
    ) -> list[carla.Transform]:
        transforms: list[carla.Transform] = []
        for carla_x, carla_y in carla_points:
            waypoint = self._lane_waypoint_at(carla_x, carla_y)
            if waypoint is not None:
                transforms.append(self._spawn_transform_from(waypoint))
        return transforms

    def _walk_lane(
        self, start_waypoint: carla.Waypoint, walk_forward: bool
    ) -> list[carla.Transform]:
        transforms: list[carla.Transform] = []
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

    def densify_along_lanes(
        self, seed_transforms: list[carla.Transform]
    ) -> list[carla.Transform]:
        densified = list(seed_transforms)
        for seed_transform in seed_transforms:
            seed_waypoint = self._lane_waypoint_at(
                seed_transform.location.x, seed_transform.location.y
            )
            if seed_waypoint is None:
                continue
            densified.extend(self._walk_lane(seed_waypoint, walk_forward=True))
            densified.extend(self._walk_lane(seed_waypoint, walk_forward=False))
        return densified

    @staticmethod
    def spaced_out(transforms: list[carla.Transform]) -> list[carla.Transform]:
        kept: list[carla.Transform] = []
        for transform in transforms:
            if all(
                transform.location.distance(existing.location) >= MINIMUM_SPAWN_GAP_METERS
                for existing in kept
            ):
                kept.append(transform)
        return kept

    def candidates_along(
        self, carla_points: list[tuple[float, float]]
    ) -> list[carla.Transform]:
        seed_transforms = self.project_onto_lanes(carla_points)
        return self.spaced_out(self.densify_along_lanes(seed_transforms))


class VehiclePopulationManager:
    def __init__(
        self,
        client: carla.Client,
        world: carla.World,
        vehicle_blueprints: list[carla.ActorBlueprint],
        coverage: MapCoverage,
        commander: TrafficManagerCommander,
        spawn_point_factory: SpawnPointFactory,
        path_pinner: RoadPathPinner,
    ) -> None:
        self._client = client
        self._world = world
        self._vehicle_blueprints = vehicle_blueprints
        self._coverage = coverage
        self._commander = commander
        self._spawn_point_factory = spawn_point_factory
        self._path_pinner = path_pinner

    @staticmethod
    def _transforms_clear_of_traffic(
        transforms: list[carla.Transform], occupied_locations: list[carla.Location]
    ) -> list[carla.Transform]:
        return [
            transform
            for transform in transforms
            if all(
                occupied.distance(transform.location) >= MINIMUM_SPAWN_GAP_METERS
                for occupied in occupied_locations
            )
        ]

    def _spawn_at(self, transform: carla.Transform) -> carla.Actor | None:
        vehicle = self._world.try_spawn_actor(
            random.choice(self._vehicle_blueprints), transform
        )
        if vehicle is None:
            return None
        vehicle.set_autopilot(True, TRAFFIC_MANAGER_PORT)
        self._commander.configure_new_vehicle(vehicle)
        return vehicle

    def destroy(self, vehicles: list[carla.Actor]) -> int:
        doomed_vehicles = [vehicle for vehicle in vehicles if vehicle.is_alive]
        if not doomed_vehicles:
            return 0
        already_gone_count = sum(
            0 if self._commander.disable_autopilot(vehicle) else 1
            for vehicle in doomed_vehicles
        )
        if already_gone_count:
            print(
                f"{LOG_PREFIX} {already_gone_count} vehicle(s) disappeared before autopilot could be released; "
                "the batch destroy still applies."
            )
        self._client.apply_batch_sync(
            [carla.command.DestroyActor(vehicle.id) for vehicle in doomed_vehicles], True
        )
        return len(doomed_vehicles)

    def cull_excess(
        self,
        vehicles: list[carla.Actor],
        target_count: int,
        polylines: list[SegmentPolyline] | None = None,
    ) -> int:
        excess_count = len(vehicles) - target_count
        if excess_count <= 0:
            return 0
        if polylines:
            ordered_vehicles = sorted(
                vehicles,
                key=lambda vehicle: distance_from_coverage(vehicle.get_location(), polylines),
                reverse=True,
            )
            print(
                f"{LOG_PREFIX} Culling the {excess_count} vehicle(s) farthest from HERE coverage first. "
            )
        else:
            ordered_vehicles = list(vehicles)
        destroyed_count = self.destroy(ordered_vehicles[:excess_count])
        print(
            f"{LOG_PREFIX} Culled {destroyed_count} vehicle(s). "
            f"Population was {len(vehicles)}, target is {target_count}. "
        )
        return destroyed_count

    def synchronise_per_segment(
        self, allocations: list[tuple[TrafficSegment, int]]
    ) -> int:
        polylines = self._coverage.polylines_of([segment for segment, _ in allocations])
        vehicles = live_vehicles(self._world)
        total_target = sum(count for _, count in allocations)

        if len(vehicles) > total_target + POPULATION_HYSTERESIS_BUFFER:
            self.cull_excess(vehicles, total_target, polylines)
            return total_target

        full_deficit = total_target - len(vehicles)
        if full_deficit <= 0:
            return total_target
        spawn_budget = min(full_deficit, MAXIMUM_SPAWNS_PER_TICK)
        if full_deficit > spawn_budget:
            print(
                f"{LOG_PREFIX} Population deficit is {full_deficit}; spawning only {spawn_budget} this tick "
                "so vehicles do not appear on top of each other and brake into a phantom jam. "
                "The rest fill over the next ticks. "
            )

        current_counts = vehicle_counts_by_polyline(vehicles, polylines)
        occupied_locations = [vehicle.get_location() for vehicle in vehicles]
        busiest_segments_first = sorted(
            range(len(allocations)),
            key=lambda index: allocations[index][0].jam_factor,
            reverse=True,
        )

        total_spawned = 0
        for index in busiest_segments_first:
            if spawn_budget <= 0:
                break
            segment, segment_target = allocations[index]
            polyline = polylines[index]
            if not polyline.carla_points:
                continue
            segment_deficit = min(
                segment_target - current_counts.get(index, 0), spawn_budget
            )
            if segment_deficit <= 0:
                continue

            candidates = self._transforms_clear_of_traffic(
                self._spawn_point_factory.candidates_along(polyline.carla_points),
                occupied_locations,
            )
            random.shuffle(candidates)

            spawned_on_segment = 0
            for candidate in candidates:
                if spawned_on_segment >= segment_deficit:
                    break
                vehicle = self._spawn_at(candidate)
                if vehicle is None:
                    continue
                self._path_pinner.pin(vehicle, polyline.carla_points)
                occupied_locations.append(vehicle.get_location())
                spawned_on_segment += 1

            total_spawned += spawned_on_segment
            spawn_budget -= spawned_on_segment
            if spawned_on_segment:
                print(
                    f"{LOG_PREFIX} {segment.description[:DESCRIPTION_PRINT_WIDTH]}: "
                    f"+{spawned_on_segment} vehicle(s) (segment target {segment_target}, "
                    f"jam factor {segment.jam_factor:.1f})."
                )

        if total_spawned:
            print(
                f"{LOG_PREFIX} Spawned {total_spawned} vehicle(s) across {len(allocations)} segment(s)."
            )
        return total_target

    def synchronise_uniform(
        self,
        target_count: int,
        auto_spawn_points: list[carla.Transform],
        coverage_anchor_points: list[tuple[float, float]],
    ) -> None:
        vehicles = live_vehicles(self._world)
        if len(vehicles) > target_count + POPULATION_HYSTERESIS_BUFFER:
            self.cull_excess(vehicles, target_count)
            return
        full_deficit = target_count - len(vehicles)
        if full_deficit <= 0:
            return

        occupied_locations = [vehicle.get_location() for vehicle in vehicles]
        candidates = self._uniform_candidates(
            auto_spawn_points, coverage_anchor_points, occupied_locations
        )
        spawn_budget = min(full_deficit, MAXIMUM_SPAWNS_PER_TICK)

        spawned_count = 0
        for candidate in candidates:
            if spawned_count >= spawn_budget:
                break
            if self._spawn_at(candidate) is not None:
                spawned_count += 1

        if spawned_count:
            print(
                f"{LOG_PREFIX} Spawned {spawned_count} vehicle(s) without per-segment geometry. "
                f"Population target: {target_count}."
            )

    def _uniform_candidates(
        self,
        auto_spawn_points: list[carla.Transform],
        coverage_anchor_points: list[tuple[float, float]],
        occupied_locations: list[carla.Location],
    ) -> list[carla.Transform]:
        free_auto_points = self._transforms_clear_of_traffic(
            auto_spawn_points, occupied_locations
        )
        if not (SPAWN_INSIDE_HERE_COVERAGE_ONLY and coverage_anchor_points):
            random.shuffle(free_auto_points)
            print(
                f"{LOG_PREFIX} Uniform spawn mode: "
                f"{len(free_auto_points)} free spawn point(s) available."
            )
            return free_auto_points

        auto_points_in_coverage = [
            transform
            for transform in free_auto_points
            if min(
                (
                    planar_distance_meters(
                        transform.location.x, transform.location.y, anchor_x, anchor_y
                    )
                    for anchor_x, anchor_y in coverage_anchor_points
                ),
                default=float("inf"),
            )
            <= HERE_COVERAGE_RADIUS_METERS
        ]
        projected_points = self._spawn_point_factory.project_onto_lanes(
            coverage_anchor_points
        )
        densified_points = self._spawn_point_factory.densify_along_lanes(projected_points)
        combined_points = self._spawn_point_factory.spaced_out(
            auto_points_in_coverage + densified_points
        )
        random.shuffle(combined_points)
        print(
            f"{LOG_PREFIX} HERE-coverage-only spawn mode: "
            f"{len(auto_points_in_coverage)} auto + {len(projected_points)} projected + "
            f"{len(densified_points) - len(projected_points)} densified = "
            f"{len(combined_points)} unique candidate(s)."
        )
        return combined_points


class VehicleRemovalRule(ABC):
    description: str = "removed"
    skips_vehicles_held_at_closure: bool = True

    def before_scan(self, world: carla.World) -> None:
        return None

    @abstractmethod
    def should_remove(self, vehicle: carla.Actor) -> bool: ...

    def after_removal(self, vehicle: carla.Actor) -> None:
        return None

    def forget_missing(self, live_vehicle_ids: set[int]) -> None:
        return None


class FellThroughMapRule(VehicleRemovalRule):
    description = "fell through the road at the map edge"
    skips_vehicles_held_at_closure = False

    def should_remove(self, vehicle: carla.Actor) -> bool:
        return vehicle.get_location().z < FALL_THROUGH_HEIGHT_METERS


class FrozenInTrafficRule(VehicleRemovalRule):
    description = "frozen in place for longer than the removal timeout"

    def __init__(self) -> None:
        self._stopped_since: dict[int, float] = {}

    def should_remove(self, vehicle: carla.Actor) -> bool:
        now = time.time()
        if (
            vehicle_speed_meters_per_second(vehicle)
            >= STOPPED_SPEED_THRESHOLD_METERS_PER_SECOND
        ):
            self._stopped_since.pop(vehicle.id, None)
            return False
        first_stopped_at = self._stopped_since.setdefault(vehicle.id, now)
        return now - first_stopped_at > FROZEN_TIMEOUT_SECONDS

    def after_removal(self, vehicle: carla.Actor) -> None:
        self._stopped_since.pop(vehicle.id, None)

    def forget_missing(self, live_vehicle_ids: set[int]) -> None:
        for vehicle_id in list(self._stopped_since):
            if vehicle_id not in live_vehicle_ids:
                self._stopped_since.pop(vehicle_id, None)


class TiltedOffRoadRule(VehicleRemovalRule):
    description = "stopped while tilted or off the drivable lane"

    def __init__(self) -> None:
        self._off_road_since: dict[int, float] = {}
        self._carla_map: carla.Map | None = None

    def before_scan(self, world: carla.World) -> None:
        self._carla_map = world.get_map()

    def should_remove(self, vehicle: carla.Actor) -> bool:
        now = time.time()
        is_stopped = (
            vehicle_speed_meters_per_second(vehicle)
            < STOPPED_SPEED_THRESHOLD_METERS_PER_SECOND
        )
        if not (is_stopped and self._is_off_the_road(vehicle)):
            self._off_road_since.pop(vehicle.id, None)
            return False
        first_seen_at = self._off_road_since.setdefault(vehicle.id, now)
        return now - first_seen_at > OFF_ROAD_GRACE_SECONDS

    def after_removal(self, vehicle: carla.Actor) -> None:
        self._off_road_since.pop(vehicle.id, None)

    def forget_missing(self, live_vehicle_ids: set[int]) -> None:
        for vehicle_id in list(self._off_road_since):
            if vehicle_id not in live_vehicle_ids:
                self._off_road_since.pop(vehicle_id, None)

    def _is_off_the_road(self, vehicle: carla.Actor) -> bool:
        if self._carla_map is None:
            return False
        transform = vehicle.get_transform()
        is_tilted = (
            abs(transform.rotation.roll) > OFF_ROAD_TILT_DEGREES
            or abs(transform.rotation.pitch) > OFF_ROAD_TILT_DEGREES
        )
        if is_tilted:
            return True
        waypoint = self._carla_map.get_waypoint(transform.location, project_to_road=True)
        if waypoint is None:
            return True
        lane_center = waypoint.transform.location
        return (
            planar_distance_meters(
                transform.location.x, transform.location.y, lane_center.x, lane_center.y
            )
            > OFF_ROAD_LANE_DISTANCE_METERS
        )


class OutsideCoverageRule(VehicleRemovalRule):
    description = "drove outside the HERE coverage this map mirrors"

    def __init__(self) -> None:
        self._polylines: list[SegmentPolyline] = []

    def set_coverage(self, polylines: list[SegmentPolyline]) -> None:
        self._polylines = [polyline for polyline in polylines if polyline.carla_points]

    def should_remove(self, vehicle: carla.Actor) -> bool:
        if not self._polylines:
            return False
        return (
            distance_from_coverage(vehicle.get_location(), self._polylines)
            > STRAY_MAX_DISTANCE_METERS
        )


class FleetSanitizer:
    def __init__(
        self,
        population_manager: VehiclePopulationManager,
        rules: list[VehicleRemovalRule],
    ) -> None:
        self._population_manager = population_manager
        self._rules = rules

    def run(self, world: carla.World, vehicle_ids_held_at_closure: set[int]) -> int:
        total_removed = 0
        for rule in self._rules:
            rule.before_scan(world)
            doomed_vehicles = [
                vehicle
                for vehicle in live_vehicles(world)
                if not (
                    rule.skips_vehicles_held_at_closure
                    and vehicle.id in vehicle_ids_held_at_closure
                )
                and rule.should_remove(vehicle)
            ]
            removed_count = self._population_manager.destroy(doomed_vehicles)
            for vehicle in doomed_vehicles:
                rule.after_removal(vehicle)
            if removed_count:
                print(f"{LOG_PREFIX} Removed {removed_count} vehicle(s): {rule.description}.")
            total_removed += removed_count
        return total_removed

    def forget_missing(self, live_vehicle_ids: set[int]) -> None:
        for rule in self._rules:
            rule.forget_missing(live_vehicle_ids)


class DashboardReporter:
    def __init__(self, map_name: str) -> None:
        self._map_name = map_name

    def print_tick(
        self,
        readings: list[DeviceReading],
        segments: list[TrafficSegment],
        active_vehicle_count: int,
        target_vehicle_count: int,
    ) -> None:
        print("\n" + "=" * 60)
        print(f"UC-01 TRAFFIC MIRROR | {self._map_name.upper()} DIGITAL TWIN")
        print(f"Timestamp      : {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(
            f"Active vehicles: {active_vehicle_count}  |  "
            f"Population target: {target_vehicle_count}"
        )
        print("-" * 60)
        self._print_devices(readings)
        self._print_segments(segments)
        print("=" * 60 + "\n")

    @staticmethod
    def _print_devices(readings: list[DeviceReading]) -> None:
        print("FIELD DEVICES:")
        for reading in readings:
            coordinates = get_device_coordinates(reading.device_id)
            coordinate_text = (
                f"({coordinates[0]:.4f}, {coordinates[1]:.4f})"
                if coordinates
                else "UNREGISTERED"
            )
            print(
                f"  {reading.device_id}  {coordinate_text}  "
                f"count={reading.count:>3}  speed={reading.speed:>5.1f} km/h"
            )

    @staticmethod
    def _print_segments(segments: list[TrafficSegment]) -> None:
        print("\nHERE FLOW ENRICHMENT:")
        if not segments:
            print("  No HERE segments received.")
            return
        average_speed_kmh = sum(segment.speed_kmh for segment in segments) / len(segments)
        average_jam_factor = sum(segment.jam_factor for segment in segments) / len(segments)
        print(f"  Segments  : {len(segments)}")
        print(f"  Avg speed : {average_speed_kmh:.1f} km/h")
        print(f"  Avg jam   : {average_jam_factor:.2f} / 10.0")
        for segment in segments:
            print(
                f"  {segment.description:<35} "
                f"speed={segment.speed_kmh:>5.1f} km/h  "
                f"jam={segment.jam_factor:.1f}  "
                f"incidents={segment.incidents_nearby}  "
                f"closed={segment.road_closure}  "
                f"[{segment.congestion_level}]"
            )


class TrafficMirrorPipeline:
    def __init__(
        self,
        world: carla.World,
        coverage: MapCoverage,
        traffic_service: TrafficService,
        speed_policy: SpeedMirrorPolicy,
        commander: TrafficManagerCommander,
        population_manager: VehiclePopulationManager,
        path_pinner: RoadPathPinner,
        outside_coverage_rule: OutsideCoverageRule,
        tick_sanitizer: FleetSanitizer,
        watchdog_sanitizer: FleetSanitizer,
        reporter: DashboardReporter,
        auto_spawn_points: list[carla.Transform],
    ) -> None:
        self._world = world
        self._coverage = coverage
        self._traffic_service = traffic_service
        self._speed_policy = speed_policy
        self._commander = commander
        self._population_manager = population_manager
        self._path_pinner = path_pinner
        self._outside_coverage_rule = outside_coverage_rule
        self._tick_sanitizer = tick_sanitizer
        self._watchdog_sanitizer = watchdog_sanitizer
        self._reporter = reporter
        self._auto_spawn_points = auto_spawn_points
        self._vehicle_ids_held_at_closure: set[int] = set()
        self._coverage_anchor_points: list[tuple[float, float]] = []
        self._device_carla_points: list[tuple[float, float]] = []

    @classmethod
    def connect(cls) -> "TrafficMirrorPipeline":
        client = carla.Client(CARLA_HOST, CARLA_PORT)
        client.set_timeout(CARLA_CLIENT_TIMEOUT_SECONDS)

        world = main_map_tool.initialize_world(client)
        main_map_tool.center_camera(world)

        traffic_manager = main_map_tool.get_traffic_manager(client)
        traffic_manager.set_synchronous_mode(False)
        traffic_manager.set_global_distance_to_leading_vehicle(
            GLOBAL_FOLLOW_DISTANCE_METERS
        )
        traffic_manager.global_percentage_speed_difference(
            DEFAULT_FALLBACK_SLOWDOWN_PERCENTAGE
        )

        coverage = MapCoverage(ACTIVE_MAP_PROFILE, GEOGRAPHIC_PROJECTOR)
        commander = TrafficManagerCommander(traffic_manager)
        path_pinner = RoadPathPinner(commander)
        spawn_point_factory = SpawnPointFactory(world)
        population_manager = VehiclePopulationManager(
            client=client,
            world=world,
            vehicle_blueprints=list(world.get_blueprint_library().filter("vehicle.*")),
            coverage=coverage,
            commander=commander,
            spawn_point_factory=spawn_point_factory,
            path_pinner=path_pinner,
        )

        outside_coverage_rule = OutsideCoverageRule()
        fell_through_map_rule = FellThroughMapRule()
        tick_sanitizer = FleetSanitizer(
            population_manager,
            [outside_coverage_rule, fell_through_map_rule, FrozenInTrafficRule()],
        )
        watchdog_sanitizer = FleetSanitizer(
            population_manager, [TiltedOffRoadRule(), fell_through_map_rule]
        )

        pipeline = cls(
            world=world,
            coverage=coverage,
            traffic_service=TrafficService(client, world),
            speed_policy=SpeedMirrorPolicy(ACTIVE_MAP_PROFILE.speed_limit_kmh),
            commander=commander,
            population_manager=population_manager,
            path_pinner=path_pinner,
            outside_coverage_rule=outside_coverage_rule,
            tick_sanitizer=tick_sanitizer,
            watchdog_sanitizer=watchdog_sanitizer,
            reporter=DashboardReporter(ACTIVE_MAP_PROFILE.name),
            auto_spawn_points=world.get_map().get_spawn_points(),
        )
        pipeline.prepare_coverage_anchors()
        return pipeline

    def prepare_coverage_anchors(self) -> None:
        device_anchors = [
            GEOGRAPHIC_PROJECTOR.to_carla_xy(latitude, longitude)
            for latitude, longitude in DEVICE_REGISTRY.values()
        ]
        self._device_carla_points = device_anchors

        segments = self._filtered_segments(self._fetch_segments())
        segment_anchors: list[tuple[float, float]] = []
        for polyline in self._coverage.polylines_of(
            self._coverage.segments_touching_map(segments)
        ):
            segment_anchors.extend(polyline.carla_points)

        if segment_anchors:
            print(
                f"{LOG_PREFIX} HERE coverage has {len(segment_anchors)} shape point(s) inside this map."
            )
            self._center_spectator_on(segment_anchors)
        else:
            print(f"{LOG_PREFIX} No HERE coverage points inside this map; spawning uniformly.")

        if device_anchors:
            print(
                f"{LOG_PREFIX} Coverage anchor set: {len(segment_anchors)} segment shape point(s) + {len(device_anchors)} field device(s)."
            )
        self._coverage_anchor_points = segment_anchors + device_anchors

    def _center_spectator_on(self, anchor_points: list[tuple[float, float]]) -> None:
        center_x = sum(anchor_x for anchor_x, _ in anchor_points) / len(anchor_points)
        center_y = sum(anchor_y for _, anchor_y in anchor_points) / len(anchor_points)
        self._world.get_spectator().set_transform(
            carla.Transform(
                carla.Location(x=center_x, y=center_y, z=SPECTATOR_HEIGHT_METERS),
                carla.Rotation(pitch=-90),
            )
        )
        print(
            f"{LOG_PREFIX} Camera centred on the mirrored road at ({center_x:.1f}, {center_y:.1f})."
        )

    def _fetch_segments(self) -> list[TrafficSegment]:
        try:
            return self._traffic_service.update(apply_speeds=False)
        except Exception as error:
            print(
                f"{LOG_PREFIX} HERE flow fetch failed ({error}). "
                "Applying the uniform fallback speed this tick."
            )
            return []


    def _filtered_segments(self, segments: list[TrafficSegment]) -> list[TrafficSegment]:
        if geo_filter_enabled():
            return self._segments_near_devices(segments)

        road_filter = road_filter_from_environment()
        if not road_filter:
            return segments
        matching_segments = [
            segment
            for segment in segments
            if road_filter.lower() in segment.description.lower()
        ]
        if matching_segments:
            return matching_segments
        print(
            f"{LOG_PREFIX} No segment matches "
            f"{ROAD_FILTER_ENVIRONMENT_VARIABLE}={road_filter!r}; using all segments."
        )
        return segments

    def _segments_near_devices(self, segments: list[TrafficSegment]) -> list[TrafficSegment]:
        if not self._device_carla_points:
            print(f"{LOG_PREFIX} Geo filter on but no device anchors yet; using all segments this pass.")
            return segments
        geometrically_near: list[TrafficSegment] = []
        for polyline in self._coverage.polylines_of(segments):
            if not polyline.carla_points:
                continue
            nearest_to_a_device = min(
                min(
                    planar_distance_meters(point_x, point_y, device_x, device_y)
                    for device_x, device_y in self._device_carla_points
                )
                for point_x, point_y in polyline.carla_points
            )
            if nearest_to_a_device <= GEO_SEGMENT_FILTER_RADIUS_METERS:
                geometrically_near.append(polyline.segment)

        if not geometrically_near:
            print(f"{LOG_PREFIX} Geo filter kept 0 segments; using all this pass to avoid an empty map.")
            return segments

        anchor_fc_text = os.environ.get(ANCHOR_FUNCTIONAL_CLASS_ENV, "")
        if anchor_fc_text:
            anchor_fc = int(anchor_fc_text)
            kept = [
                segment for segment in geometrically_near
                if segment.functional_class == 0
                or abs(segment.functional_class - anchor_fc) <= FUNCTIONAL_CLASS_TOLERANCE
            ]
            excluded_count = len(geometrically_near) - len(kept)
            if excluded_count:
                print(
                    f"{LOG_PREFIX} Functional class filter excluded {excluded_count} segment(s) "
                    f"too far from the anchor class {anchor_fc} "
                    f"(tolerance +/- {FUNCTIONAL_CLASS_TOLERANCE})."
                )
            if not kept:
                print(f"{LOG_PREFIX} Functional class filter excluded everything; using all geometrically near segments.")
                kept = geometrically_near
        else:
            kept = geometrically_near

        print(f"{LOG_PREFIX} Geo filter kept {len(kept)} of {len(segments)} segment(s) near the chosen road. ")
        return kept

    def _mirror_speeds(
        self, vehicles: list[carla.Actor], polylines: list[SegmentPolyline]
    ) -> None:
        usable_polylines = [polyline for polyline in polylines if polyline.carla_points]
        if not usable_polylines:
            fallback_command = self._speed_policy.fallback_command()
            for vehicle in vehicles:
                self._commander.apply(vehicle, fallback_command)
            self._vehicle_ids_held_at_closure.clear()
            print(
                f"{LOG_PREFIX} No mirrored geometry this tick; {len(vehicles)} vehicle(s) "
                "set to the uniform fallback speed."
            )
            return

        commanded_count = 0
        held_at_closure_count = 0
        near_incident_count = 0
        for vehicle in vehicles:
            index, _ = nearest_polyline_index(vehicle.get_location(), usable_polylines)
            if index is None:
                self._commander.apply(vehicle, self._speed_policy.fallback_command())
                continue
            segment = usable_polylines[index].segment
            command = self._speed_policy.command_for(segment)
            if not self._commander.apply(vehicle, command):
                continue
            if command.is_held_at_closure:
                self._vehicle_ids_held_at_closure.add(vehicle.id)
                held_at_closure_count += 1
            else:
                self._vehicle_ids_held_at_closure.discard(vehicle.id)
                if segment.incidents_nearby > 0:
                    near_incident_count += 1
            commanded_count += 1

        print(
            f"{LOG_PREFIX} {commanded_count} vehicle(s) mirrored across "
            f"{len(usable_polylines)} HERE segment(s) "
            f"({held_at_closure_count} held at a closure, "
            f"{near_incident_count} at an increased gap near an incident)."
        )

    def _repin_to_road(
        self, vehicles: list[carla.Actor], polylines: list[SegmentPolyline]
    ) -> None:
        usable_polylines = [
            polyline for polyline in polylines if len(polyline.carla_points) >= 2
        ]
        if not usable_polylines:
            return
        repinned_count = 0
        for vehicle in vehicles:
            if vehicle.id in self._vehicle_ids_held_at_closure:
                continue
            index, _ = nearest_polyline_index(vehicle.get_location(), usable_polylines)
            if index is None:
                continue
            if self._path_pinner.pin(vehicle, usable_polylines[index].carla_points):
                repinned_count += 1
        if repinned_count:
            print(f"{LOG_PREFIX} Re-pinned {repinned_count} vehicle(s) to the mirrored road.")

    def run_tick(self) -> None:
        readings = poll_all_devices()
        segments = self._filtered_segments(self._fetch_segments())

        segments_inside_map = self._coverage.segments_touching_map(segments)
        if segments and len(segments_inside_map) < len(segments):
            print(
                f"{LOG_PREFIX} {len(segments_inside_map)} of {len(segments)} HERE segment(s) have geometry inside this map. "
                "The vehicle budget goes to those only. "
            )
        coverage_polylines = self._coverage.polylines_of(segments_inside_map)

        if segments_inside_map:
            allocations = derive_population_targets(
                self._coverage.segments_resized_to_map(coverage_polylines),
                MAXIMUM_VEHICLE_COUNT,
            )
            target_vehicle_count = self._population_manager.synchronise_per_segment(
                allocations
            )
        else:
            target_vehicle_count = derive_target_vehicle_count(readings)
            self._population_manager.synchronise_uniform(
                target_vehicle_count, self._auto_spawn_points, self._coverage_anchor_points
            )

        vehicles = live_vehicles(self._world)
        self._mirror_speeds(vehicles, coverage_polylines)
        self._repin_to_road(vehicles, coverage_polylines)

        self._outside_coverage_rule.set_coverage(coverage_polylines)
        self._tick_sanitizer.run(self._world, self._vehicle_ids_held_at_closure)

        surviving_vehicle_ids = {vehicle.id for vehicle in live_vehicles(self._world)}
        self._vehicle_ids_held_at_closure.intersection_update(surviving_vehicle_ids)
        self._tick_sanitizer.forget_missing(surviving_vehicle_ids)
        self._watchdog_sanitizer.forget_missing(surviving_vehicle_ids)

        self._reporter.print_tick(
            readings, segments, len(surviving_vehicle_ids), target_vehicle_count
        )

    def _watch_until(self, deadline: float) -> None:
        while True:
            self._watchdog_sanitizer.run(self._world, self._vehicle_ids_held_at_closure)
            remaining_seconds = deadline - time.time()
            if remaining_seconds <= 0.0:
                return
            time.sleep(min(WATCHDOG_INTERVAL_SECONDS, remaining_seconds))

    def run_forever(self, update_interval: float = UPDATE_INTERVAL_SECONDS) -> None:
        print(f"{LOG_PREFIX} UC-01 Traffic Mirror started. Press Ctrl+C to stop.")
        try:
            while True:
                tick_started_at = time.time()
                print(
                    f"{LOG_PREFIX} Tick start {time.strftime('%H:%M:%S')}.", flush=True
                )
                self.run_tick()
                self._watch_until(tick_started_at + update_interval)
        except KeyboardInterrupt:
            print(f"\n{LOG_PREFIX} UC-01 stopped by operator.")
        except RuntimeError as error:
            print(f"\n{LOG_PREFIX} CARLA connection lost ({error}).")
            print(f"{LOG_PREFIX} Restart CARLA, then re-run this script.")


def run(update_interval: float = UPDATE_INTERVAL_SECONDS) -> None:
    TrafficMirrorPipeline.connect().run_forever(update_interval)


if __name__ == "__main__":
    run()