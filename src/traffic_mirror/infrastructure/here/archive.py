"""Auditable HERE response recording with manifest verification."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

MANIFEST_FILENAME = "manifest.json"


class PayloadFetcher(Protocol):
    def fetch(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    endpoint: str
    sequence: int
    file: str
    requested_utc: str
    source_updated: str
    result_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ArchiveVerification:
    valid: bool
    checked_snapshots: int
    errors: tuple[str, ...]


class HereArchive:
    def __init__(self, session_directory: Path, session_description: dict[str, Any]) -> None:
        self.session_directory = session_directory
        self._session_description = dict(session_description)
        self._records: list[SnapshotRecord] = []
        self._sequence_by_endpoint: dict[str, int] = {}
        self.session_directory.mkdir(parents=True, exist_ok=False)
        self._write_manifest()

    @classmethod
    def for_new_session(
        cls,
        *,
        archive_root: Path,
        map_name: str,
        bounding_box: str,
        road_filter: str = "",
        now: datetime | None = None,
    ) -> HereArchive:
        timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d_%H%M%S_%f")
        identifier = f"{map_name}_{timestamp}"
        return cls(
            archive_root / identifier,
            {
                "schema_version": 1,
                "session_id": identifier,
                "map_name": map_name,
                "bounding_box": bounding_box,
                "road_filter": road_filter,
                "created_utc": _utc_now(),
            },
        )

    def record(self, endpoint_name: str, payload: dict[str, Any]) -> Path:
        sequence = self._sequence_by_endpoint.get(endpoint_name, 0) + 1
        self._sequence_by_endpoint[endpoint_name] = sequence
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{endpoint_name}_{sequence:06d}_{timestamp}.json"
        path = self.session_directory / filename
        payload_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        _atomic_write(path, payload_bytes)
        results = payload.get("results", [])
        record = SnapshotRecord(
            endpoint=endpoint_name,
            sequence=sequence,
            file=filename,
            requested_utc=_utc_now(),
            source_updated=str(payload.get("sourceUpdated", "")),
            result_count=len(results) if isinstance(results, list) else 0,
            sha256=hashlib.sha256(payload_bytes).hexdigest(),
        )
        self._records.append(record)
        self._write_manifest()
        return path

    def _write_manifest(self) -> None:
        manifest = {
            **self._session_description,
            "snapshot_count": len(self._records),
            "snapshots": [asdict(record) for record in self._records],
        }
        _atomic_write(
            self.session_directory / MANIFEST_FILENAME,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )


class RecordingFetcher:
    def __init__(self, wrapped: PayloadFetcher, archive: HereArchive, endpoint_name: str) -> None:
        self._wrapped = wrapped
        self._archive = archive
        self._endpoint_name = endpoint_name

    def fetch(self) -> dict[str, Any]:
        payload = self._wrapped.fetch()
        self._archive.record(self._endpoint_name, payload)
        return payload


def verify_archive(session_directory: Path) -> ArchiveVerification:
    errors: list[str] = []
    try:
        manifest = json.loads((session_directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return ArchiveVerification(False, 0, (f"manifest: {type(error).__name__}",))
    snapshots = manifest.get("snapshots", [])
    if not isinstance(snapshots, list):
        return ArchiveVerification(False, 0, ("manifest: snapshots is not a list",))
    for entry in snapshots:
        try:
            path = session_directory / entry["file"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != entry["sha256"]:
                errors.append(f"{path.name}: hash mismatch")
        except (OSError, KeyError, TypeError) as error:
            errors.append(f"snapshot: {type(error).__name__}")
    if manifest.get("snapshot_count") != len(snapshots):
        errors.append("manifest: snapshot_count mismatch")
    return ArchiveVerification(not errors, len(snapshots), tuple(errors))


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)
