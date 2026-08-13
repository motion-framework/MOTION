"""Deterministic training and evaluation for OR3 behavioral risk."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from .features import build_feature_frame, build_target_series
from .schema import SESSION_COLUMN, PredictionSchemaError

RANDOM_FOREST_PARAMETERS: dict[str, int] = {
    "n_estimators": 100,
    "max_depth": 15,
    "min_samples_leaf": 5,
    "random_state": 42,
}


class TrainingError(ValueError):
    """Raised when a dataset cannot support a defensible training split."""


class SplitStrategy(StrEnum):
    SESSION_GROUPS = "session_groups"
    DETERMINISTIC_RANDOM_ROWS = "deterministic_random_rows"


class BinaryClassifier(Protocol):
    def predict(self, features: pd.DataFrame) -> Any: ...


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    strategy: SplitStrategy
    train_positions: tuple[int, ...]
    test_positions: tuple[int, ...]
    train_sessions: tuple[str, ...] = ()
    test_sessions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    accuracy: float
    precision: float
    recall: float
    f1: float
    true_negatives: int
    false_positives: int
    false_negatives: int
    true_positives: int
    support: int

    @property
    def confusion_matrix(self) -> tuple[tuple[int, int], tuple[int, int]]:
        return (
            (self.true_negatives, self.false_positives),
            (self.false_negatives, self.true_positives),
        )

    def to_dict(self) -> dict[str, float | int | list[list[int]]]:
        return {
            "accuracy": self.accuracy,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "confusion_matrix": [list(row) for row in self.confusion_matrix],
            "support": self.support,
        }


@dataclass(frozen=True, slots=True)
class TrainingResult:
    model: RandomForestClassifier
    metrics: EvaluationMetrics
    split: DatasetSplit
    training_rows: int
    evaluation_rows: int

    def training_summary(self) -> dict[str, object]:
        return {
            "split_strategy": self.split.strategy.value,
            "training_rows": self.training_rows,
            "evaluation_rows": self.evaluation_rows,
            "train_sessions": list(self.split.train_sessions),
            "test_sessions": list(self.split.test_sessions),
            "metrics": self.metrics.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class FileTrainingResult:
    """Paths and evaluation evidence produced by ``train_model_file``."""

    model_path: Path
    metadata_path: Path
    checksum_path: Path
    sha256: str
    metrics: EvaluationMetrics
    split: DatasetSplit


def build_classifier() -> RandomForestClassifier:
    """Create the fixed legacy-compatible Random Forest estimator."""

    return RandomForestClassifier(**RANDOM_FOREST_PARAMETERS)


def split_dataset(
    dataset: pd.DataFrame,
    *,
    test_size: float = 0.2,
    random_state: int = 42,
) -> DatasetSplit:
    """Split by session, falling back to deterministic rows only if absent."""

    if not 0.0 < test_size < 1.0:
        raise ValueError("test_size must be between 0 and 1")
    if len(dataset) < 2:
        raise TrainingError("At least two rows are required for a train/test split")

    positions = np.arange(len(dataset))
    if SESSION_COLUMN in dataset.columns:
        source_sessions = dataset[SESSION_COLUMN]
        if source_sessions.isna().any():
            raise PredictionSchemaError(f"{SESSION_COLUMN} must not contain null values")
        sessions = source_sessions.map(str).str.strip()
        if sessions.str.strip().eq("").any():
            raise PredictionSchemaError(f"{SESSION_COLUMN} must not contain blank values")
        unique_sessions = np.asarray(sorted(sessions.unique()), dtype=object)
        if len(unique_sessions) < 2:
            raise TrainingError(
                "session_id is present but fewer than two sessions are available; "
                "row-level fallback is intentionally disabled to prevent leakage"
            )
        splitter = GroupShuffleSplit(
            n_splits=1,
            test_size=test_size,
            random_state=random_state,
        )
        train_positions, test_positions = next(
            splitter.split(
                np.arange(len(unique_sessions)),
                groups=unique_sessions,
            )
        )
        train_session_values = tuple(str(unique_sessions[position]) for position in train_positions)
        test_session_values = tuple(str(unique_sessions[position]) for position in test_positions)
        if set(train_session_values).intersection(test_session_values):
            raise AssertionError("Session-aware split leaked a session across partitions")
        train_row_positions = np.flatnonzero(sessions.isin(train_session_values))
        test_row_positions = np.flatnonzero(sessions.isin(test_session_values))
        return DatasetSplit(
            strategy=SplitStrategy.SESSION_GROUPS,
            train_positions=tuple(int(value) for value in train_row_positions),
            test_positions=tuple(int(value) for value in test_row_positions),
            train_sessions=train_session_values,
            test_sessions=test_session_values,
        )

    train_positions, test_positions = train_test_split(
        positions,
        test_size=test_size,
        random_state=random_state,
        shuffle=True,
    )
    return DatasetSplit(
        strategy=SplitStrategy.DETERMINISTIC_RANDOM_ROWS,
        train_positions=tuple(int(value) for value in train_positions),
        test_positions=tuple(int(value) for value in test_positions),
    )


def evaluate_classifier(
    model: BinaryClassifier,
    *,
    features: pd.DataFrame,
    target: pd.Series,
) -> EvaluationMetrics:
    """Evaluate binary predictions against the supplied held-out target."""

    raw_predictions = np.asarray(model.predict(features))
    raw_expected = np.asarray(target)
    if raw_predictions.ndim != 1 or raw_predictions.shape != raw_expected.shape:
        raise TrainingError("Prediction and target arrays have incompatible shapes")
    if not np.isin(raw_predictions, (0, 1)).all():
        raise TrainingError("Classifier predictions must be binary")
    if not np.isin(raw_expected, (0, 1)).all():
        raise TrainingError("Evaluation targets must be binary")
    predictions = raw_predictions.astype(int)
    expected = raw_expected.astype(int)
    tn, fp, fn, tp = confusion_matrix(expected, predictions, labels=[0, 1]).ravel()
    return EvaluationMetrics(
        accuracy=float(accuracy_score(expected, predictions)),
        precision=float(precision_score(expected, predictions, zero_division=0)),
        recall=float(recall_score(expected, predictions, zero_division=0)),
        f1=float(f1_score(expected, predictions, zero_division=0)),
        true_negatives=int(tn),
        false_positives=int(fp),
        false_negatives=int(fn),
        true_positives=int(tp),
        support=len(expected),
    )


def train_and_evaluate(
    dataset: pd.DataFrame,
    *,
    test_size: float = 0.2,
    split_random_state: int = 42,
) -> TrainingResult:
    """Train the fixed estimator and evaluate the held-out partition."""

    features = build_feature_frame(dataset)
    target = build_target_series(dataset)
    split = split_dataset(
        dataset,
        test_size=test_size,
        random_state=split_random_state,
    )
    training_features = features.iloc[list(split.train_positions)]
    training_target = target.iloc[list(split.train_positions)]
    evaluation_features = features.iloc[list(split.test_positions)]
    evaluation_target = target.iloc[list(split.test_positions)]

    if training_target.nunique() < 2:
        raise TrainingError("The training partition must contain both target classes")

    model = build_classifier()
    model.fit(training_features, training_target)
    metrics = evaluate_classifier(
        model,
        features=evaluation_features,
        target=evaluation_target,
    )
    return TrainingResult(
        model=model,
        metrics=metrics,
        split=split,
        training_rows=len(training_features),
        evaluation_rows=len(evaluation_features),
    )


def train_model_file(
    dataset_path: Path,
    output_path: Path,
    *,
    test_size: float = 0.2,
    split_random_state: int = 42,
    provenance: Mapping[str, object] | None = None,
) -> FileTrainingResult:
    """Train from an explicit CSV and persist a versioned joblib artifact."""

    from .artifacts import ArtifactMetadata, JoblibModelRepository, sha256_file

    dataset = pd.read_csv(dataset_path)
    result = train_and_evaluate(
        dataset,
        test_size=test_size,
        split_random_state=split_random_state,
    )
    dataset_provenance: dict[str, object] = {
        "dataset_file": dataset_path.name,
        "dataset_sha256": sha256_file(dataset_path),
        "dataset_rows": len(dataset),
        "target_source": "behavioral_heuristic",
        "label_tail_policy": "legacy_zero_tail",
    }
    dataset_manifest_path = dataset_path.with_name(dataset_path.name + ".metadata.json")
    if dataset_manifest_path.is_file():
        dataset_provenance["dataset_manifest_file"] = dataset_manifest_path.name
        dataset_provenance["dataset_manifest_sha256"] = sha256_file(dataset_manifest_path)
    if provenance is not None:
        dataset_provenance["caller"] = dict(provenance)
    training_summary = result.training_summary()
    training_summary["test_size"] = test_size
    training_summary["split_random_state"] = split_random_state
    metadata = ArtifactMetadata.current(
        model=result.model,
        provenance=dataset_provenance,
        training_summary=training_summary,
    )
    saved = JoblibModelRepository(output_path).save(result.model, metadata)
    return FileTrainingResult(
        model_path=saved.path,
        metadata_path=saved.metadata_path,
        checksum_path=saved.checksum_path,
        sha256=saved.sha256,
        metrics=result.metrics,
        split=result.split,
    )
