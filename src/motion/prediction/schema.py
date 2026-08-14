"""Stable feature and dataset contracts for behavioral risk prediction."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

MODEL_FEATURES: Final[tuple[str, ...]] = (
    "speed_kmh",
    "throttle",
    "brake",
    "steer",
    "weather_rain",
)
FEATURE_NAMES: Final[tuple[str, ...]] = MODEL_FEATURES
FEATURE_SCHEMA_VERSION: Final[str] = "1.0.0"
TARGET_COLUMN: Final[str] = "incident_detected"
SESSION_COLUMN: Final[str] = "session_id"
VEHICLE_ID_COLUMN: Final[str] = "v_id"
LABEL_TAIL_POLICY: Final[str] = "legacy_zero_tail"

RAW_REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    VEHICLE_ID_COLUMN,
    "x",
    "y",
    "speed_kmh",
    "throttle",
    "brake",
    "steer",
    "collision",
)

FEATURE_RANGES: Final[Mapping[str, tuple[float | None, float | None]]] = {
    "speed_kmh": (0.0, None),
    "throttle": (0.0, 1.0),
    "brake": (0.0, 1.0),
    "steer": (-1.0, 1.0),
    "weather_rain": (0.0, 100.0),
}


class PredictionSchemaError(ValueError):
    """Raised when behavioral-prediction data violates its declared contract."""


def validate_feature_value(name: str, value: float) -> float:
    """Return a finite feature value after enforcing its physical range."""

    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as error:
        raise PredictionSchemaError(f"{name} must be numeric") from error
    if not math.isfinite(numeric_value):
        raise PredictionSchemaError(f"{name} must be finite")

    minimum, maximum = FEATURE_RANGES[name]
    if minimum is not None and numeric_value < minimum:
        raise PredictionSchemaError(f"{name} must be >= {minimum:g}")
    if maximum is not None and numeric_value > maximum:
        raise PredictionSchemaError(f"{name} must be <= {maximum:g}")
    return numeric_value


@dataclass(frozen=True, slots=True)
class VehicleObservation:
    """One simulator observation in the exact model feature schema."""

    vehicle_id: str | int
    speed_kmh: float
    throttle: float
    brake: float
    steer: float
    weather_rain: float

    def __post_init__(self) -> None:
        if not isinstance(self.vehicle_id, (str, int)) or isinstance(self.vehicle_id, bool):
            raise PredictionSchemaError("vehicle_id must be a string or integer")
        if isinstance(self.vehicle_id, str) and not self.vehicle_id.strip():
            raise PredictionSchemaError("vehicle_id must not be empty")
        for feature_name in FEATURE_NAMES:
            validated = validate_feature_value(feature_name, getattr(self, feature_name))
            object.__setattr__(self, feature_name, validated)

    def feature_values(self) -> dict[str, float]:
        """Return values ordered according to ``MODEL_FEATURES``."""

        return {name: getattr(self, name) for name in FEATURE_NAMES}
