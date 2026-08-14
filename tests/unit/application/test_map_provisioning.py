from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from motion.application.map_provisioning import MapProvisioningService
from motion.config.paths import ProjectPaths
from motion.config.runtime_state import ActiveMapState, ActiveMapStateRepository
from motion.domain.geography import BoundingBox
from motion.domain.maps import MapProfile
from motion.infrastructure.maps.artifacts import LocalMapArtifactProcessor
from motion.infrastructure.maps.geometry import (
    scan_degenerate_geometries,
    scan_object_overflows,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "maps"


class FixtureDownloader:
    def __init__(self) -> None:
        self.overwrite_values: list[bool] = []

    def download(
        self,
        _bbox: BoundingBox,
        destination_path: Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        self.overwrite_values.append(overwrite)
        if overwrite or not destination_path.exists():
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(FIXTURES / "minimal.osm", destination_path)
        return destination_path


class FixtureConverter:
    def convert(self, profile: MapProfile) -> Path:
        profile.xodr_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FIXTURES / "defective.xodr", profile.xodr_path)
        return profile.xodr_path


class FailingConverter:
    def convert(self, _profile: MapProfile) -> Path:
        raise RuntimeError("conversion failed")


def state_for(paths: ProjectPaths) -> ActiveMapState:
    return ActiveMapState.for_new_map(
        name="fixture",
        bbox=BoundingBox(40.001, 14.001, 40.002, 14.002),
        project_paths=paths,
    )


def test_provisioning_repairs_then_atomically_registers_a_map(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    downloader = FixtureDownloader()
    repository = ActiveMapStateRepository(paths.active_map_state)
    service = MapProvisioningService(
        downloader=downloader,
        converter=FixtureConverter(),
        artifact_processor=LocalMapArtifactProcessor(),
        state_repository=repository,
        project_root=paths.root,
    )

    result = service.provision(state_for(paths))

    assert result.reused_osm is False
    assert downloader.overwrite_values == [False]
    assert result.zero_length_repair.patched_count == 1
    assert result.object_overflow_repair.patched_count == 1
    assert result.remaining_degenerate_geometries == 0
    assert result.remaining_object_overflows == 0
    assert scan_degenerate_geometries(result.xodr_path)[1] == []
    assert scan_object_overflows(result.xodr_path)[1] == []
    assert repository.load() == result.state


def test_existing_osm_is_reused_only_when_it_covers_the_requested_area(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    state = state_for(paths)
    profile = state.to_profile(paths)
    profile.osm_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURES / "minimal.osm", profile.osm_path)
    downloader = FixtureDownloader()

    result = MapProvisioningService(
        downloader=downloader,
        converter=FixtureConverter(),
        artifact_processor=LocalMapArtifactProcessor(),
        state_repository=ActiveMapStateRepository(paths.active_map_state),
        project_root=paths.root,
    ).provision(state)

    assert result.reused_osm is True
    assert downloader.overwrite_values == [False]


def test_failed_conversion_never_commits_active_state(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    service = MapProvisioningService(
        downloader=FixtureDownloader(),
        converter=FailingConverter(),
        artifact_processor=LocalMapArtifactProcessor(),
        state_repository=ActiveMapStateRepository(paths.active_map_state),
        project_root=paths.root,
    )

    with pytest.raises(RuntimeError, match="conversion failed"):
        service.provision(state_for(paths))

    assert not paths.active_map_state.exists()
