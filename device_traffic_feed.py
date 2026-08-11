import random
import time

from dataclasses import dataclass, field
from typing import Optional
from map_profile import MapProfile, get_active_profile


_BASE_SPEEDS: dict[str, float] = {}

_SPEED_FALLBACK: float = 30.0     # km/h used for unregistered devices
_SPEED_NOISE_RANGE: float = 5.0   # +/- km/h random noise per reading
_COUNT_MIN: int = 3               # minimum vehicle count per observation
_COUNT_MAX: int = 15              # maximum vehicle count per observation

_SYNTHESIZED_DEVICE_COUNT: int = 4


@dataclass
class DeviceReading:
    device_id: str
    count: int
    speed: float
    timestamp: float = field(default_factory=time.time)


def _synthesize_registry(
    active_profile: MapProfile,
    device_count: int = _SYNTHESIZED_DEVICE_COUNT,
) -> dict[str, tuple[float, float]]:
    bbox = active_profile.bbox
    synthesized_registry: dict[str, tuple[float, float]] = {}

    for device_index in range(device_count):
        position_fraction = (device_index + 1) / (device_count + 1)
        latitude = bbox.south_west_lat + position_fraction * (bbox.north_east_lat - bbox.south_west_lat)
        longitude = bbox.south_west_lon + position_fraction * (bbox.north_east_lon - bbox.south_west_lon)
        synthesized_registry[f"GEN_{device_index + 1:03d}"] = (round(latitude, 6), round(longitude, 6))

    return synthesized_registry


def _resolve_device_registry(active_profile: MapProfile) -> dict[str, tuple[float, float]]:
    return active_profile.device_registry or _synthesize_registry(active_profile)


_active_profile = get_active_profile()
DEVICE_REGISTRY: dict[str, tuple[float, float]] = _resolve_device_registry(_active_profile)


def get_device_coordinates(device_id: str) -> Optional[tuple[float, float]]:
    return DEVICE_REGISTRY.get(device_id)


def simulate_device_reading(device_id: str) -> DeviceReading:
    base_speed_kmh = _BASE_SPEEDS.get(device_id, _SPEED_FALLBACK)
    speed_noise_kmh = random.uniform(-_SPEED_NOISE_RANGE, _SPEED_NOISE_RANGE)
    vehicle_count = random.randint(_COUNT_MIN, _COUNT_MAX)

    return DeviceReading(
        device_id=device_id,
        count=max(0, vehicle_count),
        speed=max(0.0, round(base_speed_kmh + speed_noise_kmh, 1)),
        timestamp=time.time(),
    )


def poll_all_devices(seed: Optional[int] = None) -> list[DeviceReading]:
    if seed is not None:
        random.seed(seed)
    return [simulate_device_reading(device_id) for device_id in DEVICE_REGISTRY]