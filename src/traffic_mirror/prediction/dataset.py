"""File-level composition for the behavioral training dataset."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from .enrichment import DEFAULT_ENRICHMENT_CONFIG, EnrichmentConfig, enrich_dataset
from .schema import (
    FEATURE_SCHEMA_VERSION,
    LABEL_TAIL_POLICY,
    SESSION_COLUMN,
    PredictionSchemaError,
)

DATASET_MANIFEST_VERSION: Final[int] = 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class DatasetInputSummary:
    source_name: str
    source_sha256: str
    session_id: str
    row_count: int
    weather_values_filled: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source_name": self.source_name,
            "source_sha256": self.source_sha256,
            "session_id": self.session_id,
            "row_count": self.row_count,
            "weather_values_filled": self.weather_values_filled,
        }


@dataclass(frozen=True, slots=True)
class DatasetBuildResult:
    output_path: Path
    metadata_path: Path
    sha256: str
    row_count: int
    input_count: int
    session_ids: tuple[str, ...]
    weather_values_filled: int


def dataset_metadata_path(output_path: Path) -> Path:
    """Return the companion JSON path for an enriched CSV."""

    return output_path.with_name(output_path.name + ".metadata.json")


def _atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        frame.to_csv(temporary_path, index=False)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_write_json(payload: dict[str, object], path: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _session_for_input(frame: pd.DataFrame, input_path: Path) -> tuple[pd.DataFrame, str]:
    result = frame.copy(deep=True)
    if SESSION_COLUMN not in result.columns:
        session_id = input_path.stem.strip()
        if not session_id:
            raise PredictionSchemaError(
                f"Cannot derive a session_id from input name {input_path.name!r}"
            )
        result[SESSION_COLUMN] = session_id
        return result, session_id

    if result[SESSION_COLUMN].isna().any():
        raise PredictionSchemaError(f"{input_path.name}: session_id must not contain null values")
    normalized = result[SESSION_COLUMN].map(str).str.strip()
    if normalized.eq("").any():
        raise PredictionSchemaError(f"{input_path.name}: session_id must not contain blank values")
    session_ids = tuple(sorted(normalized.unique()))
    if len(session_ids) != 1:
        raise PredictionSchemaError(
            f"{input_path.name}: each source file must contain exactly one session"
        )
    result[SESSION_COLUMN] = normalized
    return result, session_ids[0]


def build_dataset_files(
    inputs: Sequence[Path],
    output: Path,
    *,
    weather_rain_default: float | None = None,
    config: EnrichmentConfig = DEFAULT_ENRICHMENT_CONFIG,
) -> DatasetBuildResult:
    """Enrich and concatenate explicit CSV recordings with a provenance manifest.

    Each input is one session. If ``session_id`` is absent it is derived from
    the source filename. Session identifiers must remain unique across inputs.
    Missing rain data is filled only when ``weather_rain_default`` is supplied.
    """

    input_paths = tuple(Path(path) for path in inputs)
    if not input_paths:
        raise ValueError("At least one input CSV is required")
    output_path = Path(output)
    resolved_inputs = [path.resolve() for path in input_paths]
    if len(set(resolved_inputs)) != len(resolved_inputs):
        raise ValueError("Duplicate input paths are not allowed")
    if output_path.resolve() in resolved_inputs:
        raise ValueError("Output path must not overwrite an input CSV")

    enriched_frames: list[pd.DataFrame] = []
    summaries: list[DatasetInputSummary] = []
    seen_sessions: set[str] = set()
    for input_path in input_paths:
        frame = pd.read_csv(input_path)
        if frame.empty:
            raise PredictionSchemaError(f"{input_path.name}: input CSV is empty")
        frame, session_id = _session_for_input(frame, input_path)
        if session_id in seen_sessions:
            raise PredictionSchemaError(f"Duplicate session_id across inputs: {session_id!r}")
        seen_sessions.add(session_id)

        if "weather_rain" not in frame.columns:
            weather_values_filled = len(frame)
        else:
            weather_values_filled = int(frame["weather_rain"].isna().sum())
        enriched = enrich_dataset(
            frame,
            default_weather_rain=weather_rain_default,
            config=config,
        )
        enriched_frames.append(enriched)
        summaries.append(
            DatasetInputSummary(
                source_name=input_path.name,
                source_sha256=_sha256_file(input_path),
                session_id=session_id,
                row_count=len(enriched),
                weather_values_filled=weather_values_filled,
            )
        )

    dataset = pd.concat(enriched_frames, ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_csv(dataset, output_path)
    output_sha256 = _sha256_file(output_path)
    metadata_path = dataset_metadata_path(output_path)
    manifest: dict[str, object] = {
        "dataset_manifest_version": DATASET_MANIFEST_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "dataset_sha256": output_sha256,
        "row_count": len(dataset),
        "session_count": len(summaries),
        "weather_policy": {
            "explicit_default_provided": weather_rain_default is not None,
            "default_weather_rain": weather_rain_default,
            "values_filled": sum(item.weather_values_filled for item in summaries),
        },
        "target_policy": {
            "source": "behavioral_heuristic_not_independent_ground_truth",
            "tail": LABEL_TAIL_POLICY,
            "grouping": [SESSION_COLUMN, "v_id"],
        },
        "enrichment_config": asdict(config),
        "inputs": [item.to_dict() for item in summaries],
    }
    _atomic_write_json(manifest, metadata_path)
    return DatasetBuildResult(
        output_path=output_path,
        metadata_path=metadata_path,
        sha256=output_sha256,
        row_count=len(dataset),
        input_count=len(input_paths),
        session_ids=tuple(item.session_id for item in summaries),
        weather_values_filled=sum(item.weather_values_filled for item in summaries),
    )
