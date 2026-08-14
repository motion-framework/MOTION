from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
import pytest

from motion.prediction import artifacts
from motion.prediction.artifacts import (
    ArtifactCompatibilityError,
    ArtifactIntegrityError,
    ArtifactMetadata,
    JoblibModelRepository,
    load_trusted_legacy_model,
    sha256_file,
)
from motion.prediction.schema import MODEL_FEATURES
from motion.prediction.training import build_classifier

pytestmark = pytest.mark.filterwarnings(
    "ignore:Setting the shape on a NumPy array has been deprecated:DeprecationWarning"
)


def _fitted_model():
    features = pd.DataFrame(
        [
            {
                "speed_kmh": 10.0 + index,
                "throttle": 0.2 + (index % 2) * 0.3,
                "brake": (index % 2) * 0.8,
                "steer": 0.0,
                "weather_rain": 0.0,
            }
            for index in range(20)
        ],
        columns=MODEL_FEATURES,
    )
    return build_classifier().fit(features, [index % 2 for index in range(20)])


def _repository(tmp_path: Path) -> tuple[JoblibModelRepository, ArtifactMetadata]:
    model = _fitted_model()
    metadata = ArtifactMetadata.current(
        model=model,
        provenance={"dataset_sha256": "0" * 64, "dataset_rows": 20},
        created_at_utc="2026-08-11T00:00:00+00:00",
    )
    repository = JoblibModelRepository(tmp_path / "model.joblib")
    repository.save(model, metadata)
    return repository, metadata


def test_repository_round_trip_uses_external_metadata_and_pinned_hash(
    tmp_path: Path,
) -> None:
    repository, expected_metadata = _repository(tmp_path)
    digest = sha256_file(repository.path)

    loaded = repository.load(expected_sha256=digest)

    assert repository.metadata_path.is_file()
    assert repository.checksum_path.is_file()
    assert loaded.sha256 == digest
    assert loaded.metadata == expected_metadata
    assert tuple(loaded.model.feature_names_in_) == MODEL_FEATURES


def test_repository_detects_tampering_before_joblib_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _ = _repository(tmp_path)
    with repository.path.open("ab") as artifact_file:
        artifact_file.write(b"tampered")
    deserialized = False

    def fail_if_called(_path: Path):
        nonlocal deserialized
        deserialized = True
        raise AssertionError("joblib.load must not run")

    monkeypatch.setattr(artifacts.joblib, "load", fail_if_called)

    with pytest.raises(ArtifactIntegrityError):
        repository.load()
    assert deserialized is False


def test_metadata_feature_mismatch_is_rejected_before_joblib_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _ = _repository(tmp_path)
    document = json.loads(repository.metadata_path.read_text(encoding="utf-8"))
    document["metadata"]["feature_names"] = list(reversed(MODEL_FEATURES))
    repository.metadata_path.write_text(json.dumps(document), encoding="utf-8")
    deserialized = False

    def fail_if_called(_path: Path):
        nonlocal deserialized
        deserialized = True
        raise AssertionError("joblib.load must not run")

    monkeypatch.setattr(artifacts.joblib, "load", fail_if_called)

    with pytest.raises(ArtifactCompatibilityError, match="feature order"):
        repository.load()
    assert deserialized is False


def test_legacy_loader_requires_a_matching_out_of_band_hash(tmp_path: Path) -> None:
    path = tmp_path / "legacy.pkl"
    joblib.dump(_fitted_model(), path)

    with pytest.raises(ArtifactIntegrityError):
        load_trusted_legacy_model(path, expected_sha256="0" * 64)

    loaded = load_trusted_legacy_model(path, expected_sha256=sha256_file(path))
    assert loaded.sha256 == sha256_file(path)
