"""Small CARLA duck-typed kinematic helpers with no optional import."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def vehicle_speed_kmh(vehicle: Any) -> float:
    """Return the legacy three-dimensional velocity norm in km/h."""

    velocity = vehicle.get_velocity()
    return float(math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2) * 3.6)


def nearby_vehicle_count(
    vehicle: Any,
    vehicles: Sequence[Any],
    *,
    radius_meters: float,
) -> int:
    """Count other live actors strictly inside the requested CARLA radius."""

    location = vehicle.get_location()
    return sum(
        1
        for other in vehicles
        if other.id != vehicle.id
        and other.is_alive
        and other.get_location().distance(location) < radius_meters
    )
