"""Callable enrichment of vehicle telemetry into the legacy OR3 target."""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from .features import (
    build_feature_frame,
    coerce_numeric_columns,
    ensure_weather_rain,
    require_columns,
)
from .schema import (
    RAW_REQUIRED_COLUMNS,
    SESSION_COLUMN,
    TARGET_COLUMN,
    VEHICLE_ID_COLUMN,
    PredictionSchemaError,
)


@dataclass(frozen=True, slots=True)
class EnrichmentConfig:
    jam_velocity_kmh: float = 0.5
    stuck_window_samples: int = 10
    crash_proximity_meters: float = 15.0
    label_window_samples: int = 20
    label_shift_samples: int = 15
    hard_deceleration_delta_kmh: float = -8.0

    def __post_init__(self) -> None:
        integer_parameters = (
            self.stuck_window_samples,
            self.label_window_samples,
            self.label_shift_samples,
        )
        if not all(
            isinstance(value, int) and not isinstance(value, bool) for value in integer_parameters
        ):
            raise ValueError("enrichment window and shift parameters must be integers")
        numeric_values = (
            self.jam_velocity_kmh,
            self.crash_proximity_meters,
            self.hard_deceleration_delta_kmh,
        )
        try:
            finite_thresholds = all(math.isfinite(value) for value in numeric_values)
        except TypeError as error:
            raise ValueError("enrichment thresholds must be numeric") from error
        if not finite_thresholds:
            raise ValueError("enrichment thresholds must be finite")
        if self.jam_velocity_kmh < 0:
            raise ValueError("jam_velocity_kmh must be non-negative")
        if self.stuck_window_samples < 1:
            raise ValueError("stuck_window_samples must be at least 1")
        if self.crash_proximity_meters < 0:
            raise ValueError("crash_proximity_meters must be non-negative")
        if self.label_window_samples < 1:
            raise ValueError("label_window_samples must be at least 1")
        if self.label_shift_samples < 0:
            raise ValueError("label_shift_samples must be non-negative")
        if self.hard_deceleration_delta_kmh >= 0:
            raise ValueError("hard_deceleration_delta_kmh must be negative")


DEFAULT_ENRICHMENT_CONFIG: Final[EnrichmentConfig] = EnrichmentConfig()


def _is_supported_identifier(value: object) -> bool:
    if isinstance(value, str):
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, numbers.Real):
        return math.isfinite(float(value))
    return False


def _validate_identifier_column(frame: pd.DataFrame, column: str) -> None:
    values = frame[column]
    if values.isna().any():
        raise PredictionSchemaError(f"{column} must not contain null values")
    if values.map(lambda value: isinstance(value, str) and not value.strip()).any():
        raise PredictionSchemaError(f"{column} must not contain blank values")
    if values.map(lambda value: not _is_supported_identifier(value)).any():
        raise PredictionSchemaError(
            f"{column} must contain finite numeric or non-blank string identifiers"
        )


def _group_columns(frame: pd.DataFrame) -> list[str]:
    _validate_identifier_column(frame, VEHICLE_ID_COLUMN)
    if SESSION_COLUMN in frame.columns:
        _validate_identifier_column(frame, SESSION_COLUMN)
        return [SESSION_COLUMN, VEHICLE_ID_COLUMN]
    return [VEHICLE_ID_COLUMN]


def _jam_by_crash(
    frame: pd.DataFrame,
    *,
    proximity_meters: float,
) -> pd.Series:
    result = pd.Series(0, index=frame.index, dtype="int8")
    scenario_groups = (
        frame.groupby(SESSION_COLUMN, sort=False, dropna=False)
        if SESSION_COLUMN in frame.columns
        else ((None, frame),)
    )

    for _, scenario in scenario_groups:
        accident_points = (
            scenario.loc[scenario["collision"].eq(1), ["x", "y"]]
            .drop_duplicates()
            .to_numpy(dtype=float)
        )
        candidate_index = scenario.index[scenario["is_stuck"].eq(1) & scenario["collision"].eq(0)]
        if accident_points.size == 0 or len(candidate_index) == 0:
            continue
        candidate_points = frame.loc[candidate_index, ["x", "y"]].to_numpy(dtype=float)
        squared_distances = ((candidate_points[:, None, :] - accident_points[None, :, :]) ** 2).sum(
            axis=2
        )
        is_near_crash = (squared_distances < proximity_meters**2).any(axis=1)
        result.loc[candidate_index] = is_near_crash.astype("int8")
    return result


def enrich_dataset(
    frame: pd.DataFrame,
    *,
    default_weather_rain: float | None = None,
    config: EnrichmentConfig = DEFAULT_ENRICHMENT_CONFIG,
) -> pd.DataFrame:
    """Enrich telemetry without mutating the caller's frame.

    Labels are shifted inside each vehicle group, additionally scoped by
    ``session_id`` when present. No row can inherit a future incident from a
    different vehicle or session.
    """

    require_columns(frame, RAW_REQUIRED_COLUMNS)
    work = ensure_weather_rain(
        frame,
        default_weather_rain=default_weather_rain,
    )
    work = coerce_numeric_columns(
        work,
        (
            "timestamp",
            "x",
            "y",
            "speed_kmh",
            "throttle",
            "brake",
            "steer",
            "weather_rain",
            "collision",
        ),
    )
    if not set(work["collision"].unique()).issubset({0, 1}):
        raise PredictionSchemaError("collision must contain only 0 or 1")

    group_columns = _group_columns(work)
    original_index = frame.index.copy()
    input_order_column = "__motion_input_order__"
    while input_order_column in work.columns:
        input_order_column = "_" + input_order_column
    work[input_order_column] = np.arange(len(work))
    work = work.sort_values(
        ["timestamp", input_order_column],
        kind="mergesort",
    ).reset_index(drop=True)

    grouped = work.groupby(group_columns, sort=False, dropna=False)
    rolling_max = grouped["speed_kmh"].transform(
        lambda values: values.rolling(
            window=config.stuck_window_samples,
            min_periods=config.stuck_window_samples,
        ).max()
    )
    work["is_stuck"] = rolling_max.lt(config.jam_velocity_kmh).astype("int8")
    work["jam_by_crash"] = _jam_by_crash(
        work,
        proximity_meters=config.crash_proximity_meters,
    )
    work["jam_normal"] = (
        work["is_stuck"].eq(1) & work["jam_by_crash"].eq(0) & work["collision"].eq(0)
    ).astype("int8")
    work["base_incident"] = (work["collision"].eq(1) | work["is_stuck"].eq(1)).astype("int8")

    # Both rolling and shift execute inside the same vehicle/session group.
    grouped = work.groupby(group_columns, sort=False, dropna=False)
    work[TARGET_COLUMN] = grouped["base_incident"].transform(
        lambda values: (
            values.rolling(
                window=config.label_window_samples,
                min_periods=1,
            )
            .max()
            .shift(-config.label_shift_samples)
        )
    )
    work[TARGET_COLUMN] = work[TARGET_COLUMN].fillna(0).astype("int8")
    work["delta_speed"] = grouped["speed_kmh"].diff()
    work.loc[
        work["delta_speed"].lt(config.hard_deceleration_delta_kmh),
        TARGET_COLUMN,
    ] = 1

    # Reuse the inference-time contract so training cannot admit values the
    # deployed predictor would reject.
    canonical_features = build_feature_frame(work)
    for feature_name in canonical_features.columns:
        work[feature_name] = canonical_features[feature_name]

    result = work.sort_values(input_order_column, kind="mergesort").drop(columns=input_order_column)
    result.index = original_index
    return result
