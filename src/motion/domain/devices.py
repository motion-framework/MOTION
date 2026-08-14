"""Field-device observations and the current synthetic fallback provider."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .maps import MapProfile

SPEED_FALLBACK_KMH = 30.0
SPEED_NOISE_RANGE_KMH = 5.0
COUNT_MIN = 3
COUNT_MAX = 15
SYNTHESIZED_DEVICE_COUNT = 4


@dataclass(frozen=True, slots=True)
class DeviceReading:
    device_id: str
    count: int
    speed: float
    timestamp: float = field(default_factory=time.time)

    @property
    def speed_kmh(self) -> float:
        return self.speed


def synthesize_registry(
    active_profile: MapProfile,
    device_count: int = SYNTHESIZED_DEVICE_COUNT,
) -> dict[str, tuple[float, float]]:
    bbox = active_profile.bbox
    registry: dict[str, tuple[float, float]] = {}
    for device_index in range(device_count):
        position_fraction = (device_index + 1) / (device_count + 1)
        latitude = bbox.south_west_lat + position_fraction * (
            bbox.north_east_lat - bbox.south_west_lat
        )
        longitude = bbox.south_west_lon + position_fraction * (
            bbox.north_east_lon - bbox.south_west_lon
        )
        registry[f"GEN_{device_index + 1:03d}"] = (
            round(latitude, 6),
            round(longitude, 6),
        )
    return registry


class SyntheticDeviceProvider:
    """Generate count and speed readings for the registered device locations."""

    def __init__(
        self,
        registry: Mapping[str, tuple[float, float]],
        *,
        random_source: random.Random | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.registry = dict(registry)
        self._random = random_source or random.Random()
        self._clock = clock

    def poll(self) -> list[DeviceReading]:
        return [self._reading(device_id) for device_id in self.registry]

    def _reading(self, device_id: str) -> DeviceReading:
        speed_noise_kmh = self._random.uniform(-SPEED_NOISE_RANGE_KMH, SPEED_NOISE_RANGE_KMH)
        vehicle_count = self._random.randint(COUNT_MIN, COUNT_MAX)
        return DeviceReading(
            device_id=device_id,
            count=max(0, vehicle_count),
            speed=max(0.0, round(SPEED_FALLBACK_KMH + speed_noise_kmh, 1)),
            timestamp=self._clock(),
        )
