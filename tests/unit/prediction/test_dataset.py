from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from motion.prediction.dataset import build_dataset_files
from motion.prediction.schema import PredictionSchemaError

FIXTURES = Path(__file__).parents[2] / "fixtures" / "prediction"


def test_dataset_builder_requires_explicit_weather_default(tmp_path: Path) -> None:
    with pytest.raises(PredictionSchemaError, match="weather_rain is required"):
        build_dataset_files(
            [FIXTURES / "session_alpha.csv"],
            tmp_path / "dataset.csv",
        )


def test_dataset_builder_writes_session_provenance_and_manifest(tmp_path: Path) -> None:
    output = tmp_path / "dataset.csv"

    result = build_dataset_files(
        [
            FIXTURES / "session_alpha.csv",
            FIXTURES / "session_beta.csv",
        ],
        output,
        weather_rain_default=0.0,
    )

    dataset = pd.read_csv(output)
    manifest = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert result.row_count == 12
    assert result.session_ids == ("session_alpha", "session_beta")
    assert set(dataset["session_id"]) == {"session_alpha", "session_beta"}
    assert result.weather_values_filled == 6
    assert manifest["weather_policy"] == {
        "default_weather_rain": 0.0,
        "explicit_default_provided": True,
        "values_filled": 6,
    }
    assert manifest["target_policy"]["tail"] == "legacy_zero_tail"
    assert manifest["dataset_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert [item["source_name"] for item in manifest["inputs"]] == [
        "session_alpha.csv",
        "session_beta.csv",
    ]


def test_dataset_builder_does_not_overwrite_an_input() -> None:
    source = FIXTURES / "session_alpha.csv"

    with pytest.raises(ValueError, match="must not overwrite"):
        build_dataset_files([source], source, weather_rain_default=0.0)
