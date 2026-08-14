"""Pure policies used by UC-01 traffic mirroring."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .devices import DeviceReading
from .traffic import TrafficSegment

MINIMUM_VEHICLE_COUNT = 20
MAXIMUM_VEHICLE_COUNT = 80
DEVICE_COUNT_TO_SIMULATION_SCALE = 5

DEFAULT_FALLBACK_SLOWDOWN_PERCENTAGE = 20.0
MAXIMUM_SLOWDOWN_PERCENTAGE = 85.0
CLOSED_ROAD_SLOWDOWN_PERCENTAGE = 100.0
JAM_FACTOR_AGGRESSION_THRESHOLD = 3.0
JAM_IGNORE_VEHICLES_PERCENTAGE = 5
NORMAL_FOLLOW_DISTANCE_METERS = 2.0
INCIDENT_FOLLOW_DISTANCE_METERS = 8.0


@dataclass(frozen=True, slots=True)
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
        slowdown_percentage = (reference_speed - achievable_speed_kmh) / reference_speed * 100.0
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
        return DrivingCommand(
            slowdown_percentage=self.slowdown_percentage_for(segment),
            target_speed_kmh=self.target_speed_for(segment),
            follow_distance_meters=(
                INCIDENT_FOLLOW_DISTANCE_METERS
                if segment.incidents_nearby > 0
                else NORMAL_FOLLOW_DISTANCE_METERS
            ),
            ignore_vehicles_percentage=(
                JAM_IGNORE_VEHICLES_PERCENTAGE
                if segment.jam_factor > JAM_FACTOR_AGGRESSION_THRESHOLD
                else 0
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


def derive_target_vehicle_count(readings: Sequence[DeviceReading]) -> int:
    if not readings:
        return MINIMUM_VEHICLE_COUNT
    average_observed_count = sum(reading.count for reading in readings) / len(readings)
    scaled_count = int(average_observed_count * DEVICE_COUNT_TO_SIMULATION_SCALE)
    return max(MINIMUM_VEHICLE_COUNT, min(MAXIMUM_VEHICLE_COUNT, scaled_count))
