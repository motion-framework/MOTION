"""TrafficManager commands and road-path pinning."""

from __future__ import annotations

import math
from collections.abc import Sequence
from types import ModuleType
from typing import Any

from traffic_mirror.domain.geography import Point2D, planar_distance_meters
from traffic_mirror.domain.mirroring import (
    DEFAULT_FALLBACK_SLOWDOWN_PERCENTAGE,
    NORMAL_FOLLOW_DISTANCE_METERS,
    DrivingCommand,
)

WAYPOINT_PROBE_HEIGHT_METERS = 0.5


class CarlaTrafficManagerCommander:
    def __init__(
        self,
        traffic_manager: Any,
        carla_module: ModuleType,
        *,
        traffic_manager_port: int,
        speed_limit_kmh: float,
    ) -> None:
        self._traffic_manager = traffic_manager
        self._carla = carla_module
        self._traffic_manager_port = traffic_manager_port
        self._speed_limit_kmh = speed_limit_kmh

    def configure_new_vehicle(self, vehicle: Any) -> None:
        self._traffic_manager.distance_to_leading_vehicle(vehicle, NORMAL_FOLLOW_DISTANCE_METERS)
        self._traffic_manager.set_desired_speed(
            vehicle,
            (100.0 - DEFAULT_FALLBACK_SLOWDOWN_PERCENTAGE) / 100.0 * self._speed_limit_kmh,
        )
        self._traffic_manager.auto_lane_change(vehicle, True)
        self._traffic_manager.ignore_walkers_percentage(vehicle, 0)
        self._traffic_manager.ignore_lights_percentage(vehicle, 0)
        self._traffic_manager.ignore_signs_percentage(vehicle, 0)

    def apply(self, vehicle: Any, command: DrivingCommand) -> bool:
        try:
            self._traffic_manager.set_desired_speed(vehicle, command.target_speed_kmh)
            self._traffic_manager.distance_to_leading_vehicle(
                vehicle, command.follow_distance_meters
            )
            self._traffic_manager.ignore_vehicles_percentage(
                vehicle, command.ignore_vehicles_percentage
            )
            return True
        except RuntimeError:
            return False

    def follow_path(self, vehicle: Any, path_points: Sequence[Point2D]) -> bool:
        try:
            self._traffic_manager.set_path(
                vehicle,
                [
                    self._carla.Location(
                        x=point_x,
                        y=point_y,
                        z=WAYPOINT_PROBE_HEIGHT_METERS,
                    )
                    for point_x, point_y in path_points
                ],
            )
            return True
        except RuntimeError:
            return False

    def disable_autopilot(self, vehicle: Any) -> bool:
        try:
            vehicle.set_autopilot(False, self._traffic_manager_port)
            return True
        except RuntimeError:
            return False


class RoadPathPinner:
    def __init__(self, commander: CarlaTrafficManagerCommander) -> None:
        self._commander = commander

    def pin(self, vehicle: Any, polyline_points: Sequence[Point2D]) -> bool:
        path_ahead = self.path_in_travel_direction(vehicle, polyline_points)
        if not path_ahead:
            return False
        return self._commander.follow_path(vehicle, path_ahead)

    @staticmethod
    def path_in_travel_direction(vehicle: Any, polyline_points: Sequence[Point2D]) -> list[Point2D]:
        if len(polyline_points) < 2:
            return []
        location = vehicle.get_location()
        nearest_index = min(
            range(len(polyline_points)),
            key=lambda index: planar_distance_meters(
                location.x,
                location.y,
                polyline_points[index][0],
                polyline_points[index][1],
            ),
        )
        points_ahead = list(polyline_points[nearest_index + 1 :])
        points_behind = list(reversed(polyline_points[:nearest_index]))
        forward_vector = vehicle.get_transform().get_forward_vector()

        def alignment_with(candidate_points: list[Point2D]) -> float:
            if not candidate_points:
                return -2.0
            delta_x = candidate_points[0][0] - location.x
            delta_y = candidate_points[0][1] - location.y
            delta_length = math.hypot(delta_x, delta_y) or 1.0
            return float((delta_x * forward_vector.x + delta_y * forward_vector.y) / delta_length)

        if alignment_with(points_ahead) >= alignment_with(points_behind):
            return points_ahead
        return points_behind
