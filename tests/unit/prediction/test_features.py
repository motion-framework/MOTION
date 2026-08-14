from __future__ import annotations

import math

import pandas as pd
import pytest

from motion.prediction.features import build_feature_frame, ensure_weather_rain
from motion.prediction.schema import (
    MODEL_FEATURES,
    PredictionSchemaError,
    VehicleObservation,
)


def _feature_source() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "speed_kmh": [10.0, 20.0],
            "throttle": [0.1, 0.2],
            "brake": [0.0, 0.3],
            "steer": [-0.2, 0.2],
            "weather_rain": [5.0, 10.0],
        }
    )


def test_feature_order_is_immutable_and_canonical() -> None:
    assert isinstance(MODEL_FEATURES, tuple)
    assert MODEL_FEATURES == (
        "speed_kmh",
        "throttle",
        "brake",
        "steer",
        "weather_rain",
    )
    assert tuple(build_feature_frame(_feature_source()).columns) == MODEL_FEATURES


def test_missing_weather_requires_explicit_default() -> None:
    source = _feature_source().drop(columns="weather_rain")

    with pytest.raises(PredictionSchemaError, match="weather_rain is required"):
        build_feature_frame(source)


def test_explicit_zero_weather_default_is_honoured_without_overwriting_observed() -> None:
    source = _feature_source()
    source.loc[0, "weather_rain"] = None

    result = ensure_weather_rain(source, default_weather_rain=0.0)

    assert result["weather_rain"].tolist() == [0.0, 10.0]
    assert pd.isna(source.loc[0, "weather_rain"])


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("speed_kmh", math.inf),
        ("speed_kmh", -0.1),
        ("throttle", 1.01),
        ("brake", -0.01),
        ("steer", 1.01),
        ("weather_rain", 100.01),
    ],
)
def test_non_finite_and_out_of_range_features_fail(column: str, value: float) -> None:
    source = _feature_source()
    source.loc[0, column] = value

    with pytest.raises(PredictionSchemaError):
        build_feature_frame(source)


def test_non_numeric_weather_is_not_replaced_by_a_default() -> None:
    source = _feature_source()
    source["weather_rain"] = source["weather_rain"].astype(object)
    source.loc[0, "weather_rain"] = "unknown"

    with pytest.raises(PredictionSchemaError, match="non-numeric"):
        ensure_weather_rain(source, default_weather_rain=0.0)


@pytest.mark.parametrize("vehicle_id", [None, "", "   ", True])
def test_vehicle_observation_rejects_invalid_identifier(vehicle_id: object) -> None:
    with pytest.raises(PredictionSchemaError):
        VehicleObservation(
            vehicle_id=vehicle_id,  # type: ignore[arg-type]
            speed_kmh=10,
            throttle=0.2,
            brake=0.0,
            steer=0.0,
            weather_rain=0.0,
        )
