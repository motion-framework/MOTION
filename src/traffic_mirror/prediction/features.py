"""Pandas feature construction with explicit missing-weather handling."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from .schema import (
    FEATURE_NAMES,
    FEATURE_RANGES,
    TARGET_COLUMN,
    PredictionSchemaError,
    VehicleObservation,
    validate_feature_value,
)


def require_columns(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise PredictionSchemaError("Missing required column(s): " + ", ".join(missing))


def ensure_weather_rain(
    frame: pd.DataFrame,
    *,
    default_weather_rain: float | None = None,
) -> pd.DataFrame:
    """Return a copy with valid rain values.

    A missing column or missing cells are filled only when the caller supplies
    ``default_weather_rain`` explicitly. Non-numeric source values are always
    rejected rather than silently replaced.
    """

    result = frame.copy(deep=True)
    explicit_default = (
        validate_feature_value("weather_rain", default_weather_rain)
        if default_weather_rain is not None
        else None
    )

    if "weather_rain" not in result.columns:
        if explicit_default is None:
            raise PredictionSchemaError(
                "weather_rain is required; pass default_weather_rain explicitly "
                "only when a documented source value is unavailable"
            )
        result["weather_rain"] = explicit_default
        return result

    original = result["weather_rain"]
    numeric = pd.to_numeric(original, errors="coerce")
    invalid_non_null = original.notna() & numeric.isna()
    if invalid_non_null.any():
        raise PredictionSchemaError("weather_rain contains non-numeric values")
    if numeric.isna().any():
        if explicit_default is None:
            raise PredictionSchemaError(
                "weather_rain contains missing values; pass "
                "default_weather_rain explicitly to fill them"
            )
        numeric = numeric.fillna(explicit_default)
    result["weather_rain"] = numeric.astype(float)
    return result


def coerce_numeric_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
) -> pd.DataFrame:
    """Return a copy whose selected columns contain finite numeric values."""

    result = frame.copy(deep=True)
    require_columns(result, columns)
    for column in columns:
        original = result[column]
        numeric = pd.to_numeric(original, errors="coerce")
        if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
            raise PredictionSchemaError(f"{column} must contain finite numeric values")
        result[column] = numeric
    return result


def build_feature_frame(
    frame: pd.DataFrame,
    *,
    default_weather_rain: float | None = None,
) -> pd.DataFrame:
    """Build a validated feature matrix in canonical model order."""

    result = ensure_weather_rain(
        frame,
        default_weather_rain=default_weather_rain,
    )
    require_columns(result, FEATURE_NAMES)
    result = coerce_numeric_columns(result, FEATURE_NAMES)

    for feature_name, (minimum, maximum) in FEATURE_RANGES.items():
        values = result[feature_name]
        if minimum is not None and values.lt(minimum).any():
            raise PredictionSchemaError(f"{feature_name} contains values below {minimum:g}")
        if maximum is not None and values.gt(maximum).any():
            raise PredictionSchemaError(f"{feature_name} contains values above {maximum:g}")

    return result.loc[:, FEATURE_NAMES].astype(float)


def build_target_series(frame: pd.DataFrame) -> pd.Series:
    """Return the validated binary incident target."""

    require_columns(frame, (TARGET_COLUMN,))
    numeric = pd.to_numeric(frame[TARGET_COLUMN], errors="coerce")
    if numeric.isna().any() or not set(numeric.unique()).issubset({0, 1}):
        raise PredictionSchemaError(f"{TARGET_COLUMN} must contain only 0 or 1")
    return numeric.astype(int).rename(TARGET_COLUMN)


def observation_feature_frame(observation: VehicleObservation) -> pd.DataFrame:
    """Create the one-row feature matrix expected by scikit-learn."""

    return build_feature_frame(pd.DataFrame([observation.feature_values()]))
