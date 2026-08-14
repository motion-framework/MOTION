"""Explicit requested-area -> OSM -> OpenDRIVE -> repair -> state pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from motion.config.paths import ProjectPaths
from motion.config.runtime_state import (
    ActiveMapState,
    ActiveMapStateRepository,
)
from motion.domain.geography import BoundingBox
from motion.domain.maps import MapProfile
from motion.ports.maps import MapArtifactProcessor, MapRepairOutcome


class MapDownloader(Protocol):
    def download(
        self, bbox: BoundingBox, destination_path: Path, *, overwrite: bool = False
    ) -> Path: ...


class MapConverter(Protocol):
    def convert(self, profile: MapProfile) -> Path: ...


@dataclass(frozen=True, slots=True)
class ProvisioningResult:
    state: ActiveMapState
    osm_path: Path
    xodr_path: Path
    reused_osm: bool
    zero_length_repair: MapRepairOutcome
    object_overflow_repair: MapRepairOutcome
    remaining_degenerate_geometries: int
    remaining_object_overflows: int


class MapProvisioningService:
    def __init__(
        self,
        *,
        downloader: MapDownloader,
        converter: MapConverter,
        artifact_processor: MapArtifactProcessor,
        state_repository: ActiveMapStateRepository,
        project_root: Path,
    ) -> None:
        self._downloader = downloader
        self._converter = converter
        self._artifact_processor = artifact_processor
        self._state_repository = state_repository
        self._project_root = project_root

    def provision(self, state: ActiveMapState) -> ProvisioningResult:
        profile = state.to_profile(ProjectPaths(self._project_root))
        reused_osm = self._artifact_processor.osm_covers(profile.osm_path, profile.bbox)
        self._downloader.download(
            profile.bbox,
            profile.osm_path,
            overwrite=profile.osm_path.exists() and not reused_osm,
        )
        self._converter.convert(profile)

        processed = self._artifact_processor.repair_and_validate(profile.xodr_path)

        # Commit runtime state only after every build step produced a usable map.
        self._state_repository.save(state)
        return ProvisioningResult(
            state=state,
            osm_path=profile.osm_path,
            xodr_path=profile.xodr_path,
            reused_osm=reused_osm,
            zero_length_repair=processed.zero_length_repair,
            object_overflow_repair=processed.object_overflow_repair,
            remaining_degenerate_geometries=processed.remaining_degenerate_geometries,
            remaining_object_overflows=processed.remaining_object_overflows,
        )
