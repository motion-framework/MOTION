from __future__ import annotations

import pandas as pd
import pandas.testing as pdt
import pytest

from traffic_mirror.prediction.enrichment import EnrichmentConfig, enrich_dataset
from traffic_mirror.prediction.schema import LABEL_TAIL_POLICY, TARGET_COLUMN


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    defaults: dict[str, object] = {
        "timestamp": 0.0,
        "v_id": "vehicle",
        "x": 0.0,
        "y": 0.0,
        "speed_kmh": 20.0,
        "throttle": 0.2,
        "brake": 0.0,
        "steer": 0.0,
        "weather_rain": 0.0,
        "collision": 0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


SHIFT_ONE = EnrichmentConfig(
    stuck_window_samples=2,
    label_window_samples=1,
    label_shift_samples=1,
)


def test_shift_never_crosses_vehicle_boundary() -> None:
    source = _frame(
        [
            {"v_id": "a", "timestamp": 0},
            {"v_id": "a", "timestamp": 1},
            {"v_id": "b", "timestamp": 0, "collision": 1},
            {"v_id": "b", "timestamp": 1},
        ]
    )

    result = enrich_dataset(source, config=SHIFT_ONE)

    assert result.loc[source["v_id"].eq("a"), TARGET_COLUMN].tolist() == [0, 0]


def test_shift_never_crosses_session_boundary_for_reused_vehicle_id() -> None:
    source = _frame(
        [
            {"session_id": "s1", "v_id": 7, "timestamp": 0},
            {"session_id": "s1", "v_id": 7, "timestamp": 1},
            {
                "session_id": "s2",
                "v_id": 7,
                "timestamp": 0,
                "collision": 1,
            },
            {"session_id": "s2", "v_id": 7, "timestamp": 1},
        ]
    )

    result = enrich_dataset(source, config=SHIFT_ONE)

    assert result.loc[source["session_id"].eq("s1"), TARGET_COLUMN].tolist() == [0, 0]


def test_legacy_tail_is_zero_and_policy_is_named() -> None:
    source = _frame(
        [
            {"timestamp": 0, "collision": 1},
            {"timestamp": 1, "collision": 1},
        ]
    )

    result = enrich_dataset(source, config=SHIFT_ONE)

    assert result[TARGET_COLUMN].tolist() == [1, 0]
    assert LABEL_TAIL_POLICY == "legacy_zero_tail"


def test_unsorted_timestamps_are_processed_deterministically() -> None:
    ordered = _frame(
        [
            {"timestamp": 0, "speed_kmh": 20},
            {"timestamp": 1, "speed_kmh": 10},
            {"timestamp": 2, "speed_kmh": 10},
        ]
    )
    shuffled = ordered.iloc[[2, 0, 1]].reset_index(drop=True)

    expected = enrich_dataset(ordered, config=SHIFT_ONE).sort_values("timestamp")
    actual = enrich_dataset(shuffled, config=SHIFT_ONE).sort_values("timestamp")

    pdt.assert_frame_equal(
        actual[["timestamp", "delta_speed", TARGET_COLUMN]].reset_index(drop=True),
        expected[["timestamp", "delta_speed", TARGET_COLUMN]].reset_index(drop=True),
    )


def test_exact_legacy_thresholds_remain_strict() -> None:
    source = _frame(
        [
            {"v_id": "candidate", "timestamp": 0, "speed_kmh": 0.4, "x": 0},
            {
                "v_id": "crash",
                "timestamp": 0,
                "speed_kmh": 20,
                "x": 15,
                "collision": 1,
            },
            {"v_id": "deceleration", "timestamp": 0, "speed_kmh": 20, "x": 50},
            {"v_id": "deceleration", "timestamp": 1, "speed_kmh": 12, "x": 51},
            {"v_id": "threshold", "timestamp": 0, "speed_kmh": 0.5, "x": 100},
        ]
    )
    config = EnrichmentConfig(
        stuck_window_samples=1,
        label_window_samples=1,
        label_shift_samples=0,
    )

    result = enrich_dataset(source, config=config)

    assert result.loc[0, "is_stuck"] == 1
    assert result.loc[0, "jam_by_crash"] == 0  # distance exactly 15 m
    assert result.loc[4, "is_stuck"] == 0  # speed exactly 0.5 km/h
    assert result.loc[3, "delta_speed"] == -8
    assert result.loc[3, TARGET_COLUMN] == 0


def test_future_accident_points_are_used_within_the_same_session() -> None:
    source = _frame(
        [
            {
                "session_id": "session",
                "v_id": "candidate",
                "timestamp": 0,
                "speed_kmh": 0,
                "x": 0,
            },
            {
                "session_id": "session",
                "v_id": "crash",
                "timestamp": 10,
                "x": 1,
                "collision": 1,
            },
        ]
    )

    result = enrich_dataset(
        source,
        config=EnrichmentConfig(stuck_window_samples=1),
    )

    assert result.loc[0, "jam_by_crash"] == 1


def test_reserved_internal_column_name_is_preserved() -> None:
    source = _frame([{"__traffic_mirror_input_order__": "caller-value"}])

    result = enrich_dataset(source)

    assert result["__traffic_mirror_input_order__"].tolist() == ["caller-value"]


@pytest.mark.parametrize("threshold", [float("nan"), float("inf")])
def test_non_finite_enrichment_threshold_fails(threshold: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        EnrichmentConfig(jam_velocity_kmh=threshold)
