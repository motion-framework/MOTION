from __future__ import annotations

import hashlib
import json
import os
import time

from dataclasses import dataclass
from datetime import datetime, timezone


ARCHIVE_ROOT = "DataHERE"
MANIFEST_FILENAME = "manifest.json"
SEQUENCE_DIGITS = 6
JSON_INDENT = 2


def _utc_timestamp_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _filesystem_timestamp_text() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


@dataclass(frozen=True)
class SnapshotRecord:
    endpoint_name: str
    sequence_number: int
    filename: str
    requested_utc: str
    source_updated: str
    result_count: int
    sha256: str

    def to_dictionary(self) -> dict:
        return {
            "endpoint": self.endpoint_name,
            "sequence": self.sequence_number,
            "file": self.filename,
            "requested_utc": self.requested_utc,
            "source_updated": self.source_updated,
            "result_count": self.result_count,
            "sha256": self.sha256,
        }


class HereArchive:
    def __init__(self, session_directory: str, session_description: dict) -> None:
        self._session_directory = session_directory
        self._session_description = session_description
        self._records: list[SnapshotRecord] = []
        self._sequence_by_endpoint: dict[str, int] = {}

        os.makedirs(self._session_directory, exist_ok=True)
        self._write_manifest()
        print(f"[here_archive] Recording HERE responses into: {self._session_directory}")

    @classmethod
    def for_new_session(
        cls,
        map_name: str,
        bounding_box: str,
        road_filter: str = "",
    ) -> "HereArchive":
        session_identifier = f"{map_name}_{_filesystem_timestamp_text()}"
        session_directory = os.path.join(ARCHIVE_ROOT, session_identifier)

        return cls(
            session_directory=session_directory,
            session_description={
                "session_id": session_identifier,
                "map_name": map_name,
                "bounding_box": bounding_box,
                "road_filter": road_filter,
                "created_utc": _utc_timestamp_text(),
            },
        )

    def record(self, endpoint_name: str, payload: dict) -> str:
        sequence_number = self._sequence_by_endpoint.get(endpoint_name, 0) + 1
        self._sequence_by_endpoint[endpoint_name] = sequence_number

        filename = (
            f"{endpoint_name}_"
            f"{sequence_number:0{SEQUENCE_DIGITS}d}_"
            f"{_filesystem_timestamp_text()}.json"
        )
        file_path = os.path.join(self._session_directory, filename)
        payload_text = json.dumps(payload, ensure_ascii=False, indent=JSON_INDENT)
        payload_bytes = payload_text.encode("utf-8")

        with open(file_path, "wb") as snapshot_file:
            snapshot_file.write(payload_bytes)

        record = SnapshotRecord(
            endpoint_name=endpoint_name,
            sequence_number=sequence_number,
            filename=filename,
            requested_utc=_utc_timestamp_text(),
            source_updated=str(payload.get("sourceUpdated", "")),
            result_count=len(payload.get("results", [])),
            sha256=hashlib.sha256(payload_bytes).hexdigest(),
        )
        self._records.append(record)
        self._write_manifest()

        print(
            f"[here_archive] Saved {endpoint_name} snapshot {sequence_number} "
            f"({record.result_count} results, {len(payload_bytes) / 1024:.0f} KB) "
            f"-> {filename}"
        )
        return file_path

    def _write_manifest(self) -> None:
        manifest = dict(self._session_description)
        manifest["snapshot_count"] = len(self._records)
        manifest["snapshots"] = [record.to_dictionary() for record in self._records]

        manifest_path = os.path.join(self._session_directory, MANIFEST_FILENAME)
        with open(manifest_path, "w", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, ensure_ascii=False, indent=JSON_INDENT)
