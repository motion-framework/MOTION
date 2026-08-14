from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from motion.prediction.schema import MODEL_FEATURES
from motion.prediction.training import (
    RANDOM_FOREST_PARAMETERS,
    SplitStrategy,
    TrainingError,
    split_dataset,
    train_and_evaluate,
    train_model_file,
)


def _training_dataset(*, include_sessions: bool = True) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for session_index in range(6):
        for row_index in range(12):
            target = row_index % 2
            row: dict[str, object] = {
                "speed_kmh": 10.0 + row_index + session_index,
                "throttle": 0.2 + target * 0.3,
                "brake": target * 0.7,
                "steer": (row_index % 5 - 2) / 10,
                "weather_rain": session_index * 10.0,
                "incident_detected": target,
            }
            if include_sessions:
                row["session_id"] = f"session-{session_index}"
            rows.append(row)
    return pd.DataFrame(rows)


def test_train_and_test_sessions_are_disjoint_and_order_independent() -> None:
    dataset = _training_dataset()
    shuffled = dataset.sample(frac=1, random_state=99).reset_index(drop=True)

    first = split_dataset(dataset, test_size=0.34)
    second = split_dataset(shuffled, test_size=0.34)

    assert first.strategy is SplitStrategy.SESSION_GROUPS
    assert set(first.train_sessions).isdisjoint(first.test_sessions)
    assert first.train_sessions == second.train_sessions
    assert first.test_sessions == second.test_sessions


def test_single_session_fails_instead_of_falling_back_to_rows() -> None:
    dataset = _training_dataset()
    dataset["session_id"] = "only-session"

    with pytest.raises(TrainingError, match=r"row-level fallback.*disabled"):
        split_dataset(dataset)


def test_random_row_fallback_is_deterministic_only_when_session_is_absent() -> None:
    dataset = _training_dataset(include_sessions=False)

    first = split_dataset(dataset)
    second = split_dataset(dataset)

    assert first.strategy is SplitStrategy.DETERMINISTIC_RANDOM_ROWS
    assert first.train_positions == second.train_positions
    assert first.test_positions == second.test_positions


def test_random_forest_contract_and_training_are_exact() -> None:
    result = train_and_evaluate(_training_dataset(), test_size=0.34)
    parameters = result.model.get_params()

    assert tuple(result.model.feature_names_in_) == MODEL_FEATURES
    assert {name: parameters[name] for name in RANDOM_FOREST_PARAMETERS} == {
        "n_estimators": 100,
        "max_depth": 15,
        "min_samples_leaf": 5,
        "random_state": 42,
    }
    assert parameters["class_weight"] is None
    assert result.metrics.support == result.evaluation_rows


def test_train_model_file_matches_cli_contract_and_writes_sidecars(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "dataset.csv"
    model_path = tmp_path / "model.pkl"
    _training_dataset().to_csv(dataset_path, index=False)
    manifest_path = dataset_path.with_name(dataset_path.name + ".metadata.json")
    manifest_path.write_text('{"dataset_manifest_version": 1}\n', encoding="utf-8")

    result = train_model_file(dataset_path, model_path, test_size=0.34)
    metadata_document = json.loads(result.metadata_path.read_text(encoding="utf-8"))

    assert result.model_path == model_path
    assert result.model_path.is_file()
    assert result.metadata_path.is_file()
    assert result.checksum_path.is_file()
    assert result.metrics.support > 0
    metadata = metadata_document["metadata"]
    assert metadata["estimator_parameters"]["class_weight"] is None
    assert metadata["training_summary"]["split_random_state"] == 42
    assert metadata["provenance"]["dataset_manifest_file"] == manifest_path.name
