"""Application-facing contracts for local OSM/OpenDRIVE artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from traffic_mirror.domain.geography import BoundingBox


@dataclass(frozen=True, slots=True)
class MapRepairOutcome:
    patched_count: int
    backup_path: Path | None


@dataclass(frozen=True, slots=True)
class MapArtifactProcessingResult:
    zero_length_repair: MapRepairOutcome
    object_overflow_repair: MapRepairOutcome
    remaining_degenerate_geometries: int
    remaining_object_overflows: int


class MapArtifactProcessor(Protocol):
    """Inspect reusable OSM input and repair/validate converted OpenDRIVE."""

    def osm_covers(self, path: Path, bbox: BoundingBox) -> bool: ...

    def repair_and_validate(self, path: Path) -> MapArtifactProcessingResult: ...
