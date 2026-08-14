"""Versioned joblib persistence with pre-deserialization verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Final

import joblib

from .schema import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, TARGET_COLUMN
from .training import RANDOM_FOREST_PARAMETERS

ARTIFACT_FORMAT_VERSION: Final[int] = 1
SHA256_HEX_LENGTH: Final[int] = 64
LEGACY_REFERENCE_MODEL_SHA256: Final[str] = (
    "f938acd67bb0fda0b63027865167564452331fb692d80aba9ad820515cfbeec2"
)
REPOSITORY_ESTIMATOR_PARAMETERS: Final[dict[str, object]] = {
    **RANDOM_FOREST_PARAMETERS,
    "class_weight": None,
}


class ArtifactError(RuntimeError):
    """Base error for model artifact persistence."""


class ArtifactIntegrityError(ArtifactError):
    """Raised before deserialization when an artifact checksum is invalid."""


class ArtifactCompatibilityError(ArtifactError):
    """Raised when artifact metadata is incompatible with the code schema."""


def sha256_file(path: Path) -> str:
    """Calculate a file SHA-256 incrementally."""

    digest = hashlib.sha256()
    with path.open("rb") as artifact_file:
        for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_digest(value: str, *, field_name: str) -> str:
    digest = value.strip().lower()
    if len(digest) != SHA256_HEX_LENGTH or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ArtifactIntegrityError(f"{field_name} is not a SHA-256 digest")
    return digest


def _installed_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for distribution in (
        "motion",
        "scikit-learn",
        "numpy",
        "pandas",
        "joblib",
    ):
        try:
            result[distribution] = version(distribution)
        except PackageNotFoundError:
            result[distribution] = "source-checkout"
    return result


def _json_compatible_mapping(
    value: Mapping[str, object],
    *,
    field_name: str,
) -> dict[str, object]:
    try:
        normalized = json.loads(json.dumps(dict(value), sort_keys=True))
    except (TypeError, ValueError) as error:
        raise ArtifactCompatibilityError(
            f"{field_name} must contain JSON-compatible provenance data"
        ) from error
    if not isinstance(normalized, dict):
        raise ArtifactCompatibilityError(f"{field_name} must be a mapping")
    return normalized


def _object_mapping(value: object, *, field_name: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ArtifactCompatibilityError(f"{field_name} must be a string-keyed mapping")
    return {key: item for key, item in value.items()}


def _string_mapping(value: object, *, field_name: str) -> dict[str, str]:
    mapping = _object_mapping(value, field_name=field_name)
    if not all(isinstance(item, str) for item in mapping.values()):
        raise ArtifactCompatibilityError(f"{field_name} values must be strings")
    return {key: item for key, item in mapping.items() if isinstance(item, str)}


def _string_value(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ArtifactCompatibilityError(f"{field_name} must be a string")
    return value


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    artifact_format_version: int
    feature_schema_version: str
    feature_names: tuple[str, ...]
    target_column: str
    estimator_type: str
    estimator_parameters: dict[str, object]
    created_at_utc: str
    library_versions: dict[str, str]
    training_summary: dict[str, object]
    provenance: dict[str, object]

    @classmethod
    def current(
        cls,
        *,
        model: Any,
        provenance: Mapping[str, object],
        training_summary: Mapping[str, object] | None = None,
        created_at_utc: str | None = None,
    ) -> ArtifactMetadata:
        parameters: dict[str, Any] = dict(getattr(model, "get_params", lambda: {})())
        selected_parameters = {
            name: parameters.get(name) for name in REPOSITORY_ESTIMATOR_PARAMETERS
        }
        return cls(
            artifact_format_version=ARTIFACT_FORMAT_VERSION,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            feature_names=FEATURE_NAMES,
            target_column=TARGET_COLUMN,
            estimator_type=type(model).__name__,
            estimator_parameters=selected_parameters,
            created_at_utc=created_at_utc or datetime.now(UTC).isoformat(),
            library_versions=_installed_versions(),
            training_summary=_json_compatible_mapping(
                training_summary or {},
                field_name="training_summary",
            ),
            provenance=_json_compatible_mapping(
                provenance,
                field_name="provenance",
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_format_version": self.artifact_format_version,
            "feature_schema_version": self.feature_schema_version,
            "feature_names": list(self.feature_names),
            "target_column": self.target_column,
            "estimator_type": self.estimator_type,
            "estimator_parameters": dict(self.estimator_parameters),
            "created_at_utc": self.created_at_utc,
            "library_versions": dict(self.library_versions),
            "training_summary": dict(self.training_summary),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ArtifactMetadata:
        try:
            artifact_format_version = payload["artifact_format_version"]
            feature_schema_version = payload["feature_schema_version"]
            feature_names = payload["feature_names"]
            target_column = payload["target_column"]
            estimator_type = payload["estimator_type"]
            estimator_parameters = payload["estimator_parameters"]
            created_at_utc = payload["created_at_utc"]
            library_versions = payload["library_versions"]
            training_summary = payload["training_summary"]
            provenance = payload["provenance"]
            if not isinstance(artifact_format_version, int) or isinstance(
                artifact_format_version, bool
            ):
                raise TypeError
            if not isinstance(feature_names, list) or not all(
                isinstance(value, str) for value in feature_names
            ):
                raise TypeError
            return cls(
                artifact_format_version=artifact_format_version,
                feature_schema_version=_string_value(
                    feature_schema_version,
                    field_name="feature_schema_version",
                ),
                feature_names=tuple(feature_names),
                target_column=_string_value(
                    target_column,
                    field_name="target_column",
                ),
                estimator_type=_string_value(
                    estimator_type,
                    field_name="estimator_type",
                ),
                estimator_parameters=_object_mapping(
                    estimator_parameters,
                    field_name="estimator_parameters",
                ),
                created_at_utc=_string_value(
                    created_at_utc,
                    field_name="created_at_utc",
                ),
                library_versions=_string_mapping(
                    library_versions,
                    field_name="library_versions",
                ),
                training_summary=_object_mapping(
                    training_summary,
                    field_name="training_summary",
                ),
                provenance=_object_mapping(
                    provenance,
                    field_name="provenance",
                ),
            )
        except (KeyError, TypeError) as error:
            raise ArtifactCompatibilityError("Invalid model artifact metadata") from error


@dataclass(frozen=True, slots=True)
class SavedArtifact:
    path: Path
    metadata_path: Path
    checksum_path: Path
    sha256: str
    metadata: ArtifactMetadata


@dataclass(frozen=True, slots=True)
class LoadedArtifact:
    model: Any
    metadata: ArtifactMetadata
    sha256: str


@dataclass(frozen=True, slots=True)
class LoadedLegacyArtifact:
    model: Any
    sha256: str


def _validate_metadata(metadata: ArtifactMetadata) -> None:
    if metadata.artifact_format_version != ARTIFACT_FORMAT_VERSION:
        raise ArtifactCompatibilityError("Unsupported artifact format version")
    if metadata.feature_schema_version != FEATURE_SCHEMA_VERSION:
        raise ArtifactCompatibilityError("Artifact feature schema version is incompatible")
    if metadata.feature_names != FEATURE_NAMES:
        raise ArtifactCompatibilityError("Artifact feature order is incompatible")
    if metadata.target_column != TARGET_COLUMN:
        raise ArtifactCompatibilityError("Artifact target column is incompatible")
    if metadata.estimator_type != "RandomForestClassifier":
        raise ArtifactCompatibilityError("Artifact estimator type is incompatible")
    if metadata.estimator_parameters != REPOSITORY_ESTIMATOR_PARAMETERS:
        raise ArtifactCompatibilityError(
            "Artifact estimator parameters do not match the OR3 model contract"
        )


def _validate_model(
    model: Any,
    *,
    require_current_class_weight: bool = True,
) -> None:
    if not callable(getattr(model, "predict", None)):
        raise ArtifactCompatibilityError("Artifact model does not implement predict")
    if type(model).__name__ != "RandomForestClassifier":
        raise ArtifactCompatibilityError("Artifact model type is incompatible")
    feature_names = getattr(model, "feature_names_in_", None)
    if feature_names is None:
        raise ArtifactCompatibilityError("Model does not record named input features")
    if tuple(str(value) for value in feature_names) != FEATURE_NAMES:
        raise ArtifactCompatibilityError("Model feature_names_in_ is incompatible")
    feature_count = getattr(model, "n_features_in_", None)
    if feature_count is None:
        raise ArtifactCompatibilityError("Model does not record its input feature count")
    if int(feature_count) != len(FEATURE_NAMES):
        raise ArtifactCompatibilityError("Model feature count is incompatible")
    classes = getattr(model, "classes_", None)
    if classes is None:
        raise ArtifactCompatibilityError("Model does not record fitted classes")
    if tuple(classes) != (0, 1):
        raise ArtifactCompatibilityError("Model classes are incompatible")
    parameters: dict[str, Any] = dict(getattr(model, "get_params", lambda: {})())
    selected = {name: parameters.get(name) for name in RANDOM_FOREST_PARAMETERS}
    if selected != RANDOM_FOREST_PARAMETERS:
        raise ArtifactCompatibilityError(
            "Model estimator parameters do not match the OR3 model contract"
        )
    if require_current_class_weight and parameters.get("class_weight") is not None:
        raise ArtifactCompatibilityError(
            "Model class_weight does not match the current OR3 training contract"
        )


def _atomic_write_text(path: Path, contents: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_text(contents, encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


class JoblibModelRepository:
    """Persist a trusted model with external metadata and checksum sidecars.

    Joblib uses pickle semantics. The JSON metadata and SHA-256 sidecar are
    parsed and validated before deserialization. A checksum detects corruption,
    not authenticity; callers should pin ``expected_sha256`` out of band.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def metadata_path(self) -> Path:
        return self.path.with_name(self.path.name + ".metadata.json")

    @property
    def checksum_path(self) -> Path:
        return self.path.with_name(self.path.name + ".sha256")

    def save(self, model: Any, metadata: ArtifactMetadata) -> SavedArtifact:
        _validate_metadata(metadata)
        _validate_model(model)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=self.path.name + ".",
            suffix=".tmp",
            dir=self.path.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            joblib.dump(model, temporary_path, compress=3)
            digest = sha256_file(temporary_path)
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

        metadata_document = {
            "artifact_format_version": ARTIFACT_FORMAT_VERSION,
            "model_sha256": digest,
            "metadata": metadata.to_dict(),
        }
        _atomic_write_text(
            self.metadata_path,
            json.dumps(metadata_document, indent=2, sort_keys=True) + "\n",
        )
        _atomic_write_text(
            self.checksum_path,
            f"{digest}  {self.path.name}\n",
        )
        return SavedArtifact(
            path=self.path,
            metadata_path=self.metadata_path,
            checksum_path=self.checksum_path,
            sha256=digest,
            metadata=metadata,
        )

    def load(self, *, expected_sha256: str | None = None) -> LoadedArtifact:
        """Validate JSON and every digest before invoking ``joblib.load``."""

        metadata, metadata_digest = self._read_metadata()
        recorded_digest = self._read_checksum()
        actual_digest = sha256_file(self.path)
        for field_name, candidate in (
            ("metadata model_sha256", metadata_digest),
            ("checksum sidecar", recorded_digest),
        ):
            if not hmac.compare_digest(candidate, actual_digest):
                raise ArtifactIntegrityError(f"Artifact SHA-256 does not match {field_name}")
        if expected_sha256 is not None:
            expected = _validate_digest(expected_sha256, field_name="expected_sha256")
            if not hmac.compare_digest(expected, actual_digest):
                raise ArtifactIntegrityError("Artifact SHA-256 does not match the pinned digest")

        try:
            model = joblib.load(self.path)
        except Exception as error:
            raise ArtifactCompatibilityError("Cannot deserialize model artifact") from error
        _validate_model(model)
        return LoadedArtifact(model=model, metadata=metadata, sha256=actual_digest)

    def _read_metadata(self) -> tuple[ArtifactMetadata, str]:
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise TypeError
            if payload.get("artifact_format_version") != ARTIFACT_FORMAT_VERSION:
                raise ArtifactCompatibilityError("Unsupported metadata document version")
            metadata_payload = payload["metadata"]
            if not isinstance(metadata_payload, dict):
                raise TypeError
            metadata = ArtifactMetadata.from_dict(metadata_payload)
            metadata_digest = _validate_digest(
                str(payload["model_sha256"]),
                field_name="metadata model_sha256",
            )
        except ArtifactError:
            raise
        except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError, TypeError) as error:
            raise ArtifactCompatibilityError(
                "Artifact metadata sidecar is missing or invalid"
            ) from error
        _validate_metadata(metadata)
        return metadata, metadata_digest

    def _read_checksum(self) -> str:
        try:
            token = self.checksum_path.read_text(encoding="ascii").split()[0]
        except (FileNotFoundError, OSError, IndexError) as error:
            raise ArtifactIntegrityError(
                "Artifact checksum sidecar is missing or invalid"
            ) from error
        return _validate_digest(token, field_name="Artifact checksum sidecar")


def load_trusted_legacy_model(
    path: Path,
    *,
    expected_sha256: str,
) -> LoadedLegacyArtifact:
    """Load a legacy bare pickle only after matching an out-of-band digest.

    This explicit compatibility path cannot supply modern metadata. It is
    intended only for a known, trusted legacy artifact such as the reference
    model documented in ``docs/model-card.md``.
    """

    expected = _validate_digest(expected_sha256, field_name="expected_sha256")
    actual = sha256_file(path)
    if not hmac.compare_digest(expected, actual):
        raise ArtifactIntegrityError("Legacy artifact does not match the pinned digest")
    try:
        model = joblib.load(path)
    except Exception as error:
        raise ArtifactCompatibilityError("Cannot deserialize legacy model artifact") from error
    _validate_model(model, require_current_class_weight=False)
    return LoadedLegacyArtifact(model=model, sha256=actual)
