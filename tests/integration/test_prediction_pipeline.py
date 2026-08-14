from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from motion.cli import main
from motion.prediction.artifacts import JoblibModelRepository
from motion.prediction.dataset import build_dataset_files
from motion.prediction.inference import predict_incident
from motion.prediction.schema import FEATURE_NAMES, VehicleObservation
from motion.prediction.training import SplitStrategy, train_model_file


def _write_session(path: Path, session_index: int) -> None:
    rows: list[dict[str, float | int | str]] = []
    for sample_index in range(60):
        collision = int(sample_index == 30)
        rows.append(
            {
                "timestamp": sample_index * 0.5,
                "v_id": f"vehicle-{session_index}",
                "x": float(sample_index),
                "y": float(session_index * 20),
                "speed_kmh": 2.0 if 25 <= sample_index <= 32 else 30.0,
                "throttle": 0.1 if collision else 0.5,
                "brake": 0.9 if collision else 0.0,
                "steer": 0.0,
                "weather_rain": float(session_index * 5),
                "collision": collision,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def test_csv_to_trusted_model_to_prediction_flow(tmp_path) -> None:
    inputs = []
    for session_index in range(5):
        path = tmp_path / f"session-{session_index}.csv"
        _write_session(path, session_index)
        inputs.append(path)

    dataset_path = tmp_path / "behavioral.csv"
    dataset_result = build_dataset_files(inputs, dataset_path)
    manifest = json.loads(dataset_result.metadata_path.read_text(encoding="utf-8"))

    assert dataset_result.row_count == 300
    assert manifest["session_count"] == 5
    assert manifest["dataset_sha256"] == dataset_result.sha256

    model_path = tmp_path / "models" / "traffic_aimodel.pkl"
    training_result = train_model_file(dataset_path, model_path, test_size=0.4)

    assert training_result.split.strategy is SplitStrategy.SESSION_GROUPS
    assert set(training_result.split.train_sessions).isdisjoint(training_result.split.test_sessions)
    assert training_result.metrics.support > 0

    loaded = JoblibModelRepository(model_path).load(expected_sha256=training_result.sha256)
    assert loaded.metadata.feature_names == FEATURE_NAMES
    prediction = predict_incident(
        loaded.model,
        VehicleObservation(
            vehicle_id="integration-vehicle",
            speed_kmh=20.0,
            throttle=0.2,
            brake=0.1,
            steer=0.0,
            weather_rain=10.0,
        ),
    )
    assert prediction.vehicle_id == "integration-vehicle"
    assert isinstance(prediction.incident_detected, bool)


def test_documented_dataset_and_training_cli_commands(tmp_path, capsys) -> None:
    inputs = []
    for session_index in range(5):
        path = tmp_path / f"cli-session-{session_index}.csv"
        _write_session(path, session_index)
        inputs.append(path)
    dataset_path = tmp_path / "cli-behavioral.csv"
    model_path = tmp_path / "cli-model.pkl"

    assert (
        main(
            [
                "dataset",
                "build",
                *(str(path) for path in inputs),
                "--output",
                str(dataset_path),
            ]
        )
        == 0
    )
    assert "Wrote 300 rows" in capsys.readouterr().out

    assert (
        main(
            [
                "model",
                "train",
                "--dataset",
                str(dataset_path),
                "--output",
                str(model_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert f"Model: {model_path}" in output
    assert "Accuracy:" in output
    assert model_path.is_file()
    assert model_path.with_name(model_path.name + ".metadata.json").is_file()
    assert model_path.with_name(model_path.name + ".sha256").is_file()
