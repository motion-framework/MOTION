"""Shared UC-02/UC-03 workflow: propose -> stage -> apply.

This is the counterpart of ``application.map_provisioning`` and
``application.road_selection`` for scenario simulation: it reuses both
verbatim, plus the exact HERE-fetch-and-select glue ``motion mirror-road``
already performs, so both UC-02 (What-If Scenario Editor) and UC-03
(Infrastructure Event Simulation) share one implementation instead of two.

Unlike UC-01's own provisioning, functions here never commit to the shared
``var/runtime/active_map.json`` active-map pointer for a *modified* map --
only the baseline provisioning step does, because the baseline legitimately
is "the active map" UC-01 would mirror (see docs/architecture.md). The
modified variant is tracked by its own ``ScenarioRecord``
(``config.scenario_state``) instead.
"""

from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from motion.config.runtime_state import ActiveMapState
from motion.domain.devices import DeviceReading, SyntheticDeviceProvider
from motion.domain.geography import BoundingBox
from motion.domain.mirroring import derive_target_vehicle_count
from motion.domain.traffic import TrafficSegment
from motion.ports.maps import MapArtifactProcessingResult, MapArtifactProcessor

from .map_provisioning import MapConverter, MapProvisioningService, ProvisioningResult
from .road_selection import (
    build_map_state_for_road,
    choose_road_interactively,
    group_by_road,
    representative_segment,
    segments_near_center,
    select_main_road_segment,
)

if TYPE_CHECKING:
    from motion.config.paths import ProjectPaths
    from motion.config.settings import AppSettings
    from motion.domain.maps import MapProfile
    from motion.ports.traffic import TrafficDataProvider


@dataclass(frozen=True, slots=True)
class BaselineProposal:
    """The real-world area/road UC-02/UC-03 propose, plus its provisioned map."""

    state: ActiveMapState
    segment: TrafficSegment
    provisioning: ProvisioningResult
    device_readings: tuple[DeviceReading, ...]
    estimated_vehicle_count: int


def propose_and_provision_baseline(
    *,
    settings: AppSettings,
    lat: float,
    lon: float,
    radius_meters: float,
    map_name: str,
    geo: bool,
    input_reader: Callable[[str], str] = input,
) -> BaselineProposal:
    """Select a HERE road and provision it as the baseline map.

    Reuses the exact ``application.road_selection`` functions and the
    unmodified ``MapProvisioningService`` that ``motion map mirror-road``
    already uses, so the baseline map legitimately becomes the active map
    (matching the UC-02 precondition "UC-01 active / real baseline
    available"). Also polls the newly registered device positions (the "fake
    device" estimate) to report a current vehicle-count estimate alongside
    the proposal.
    """

    from motion.infrastructure.here.client import HereEndpointFetcher, RequestsJsonTransport
    from motion.infrastructure.here.parser import TrafficParser

    if radius_meters <= 0:
        raise ValueError("radius_meters must be positive.")
    search_bbox = BoundingBox.from_center(lat, lon, radius_meters)
    fetcher = HereEndpointFetcher(
        transport=RequestsJsonTransport(),
        api_key=settings.here.api_key,
        bbox=search_bbox.to_here_bbox(),
        url=settings.here.flow_url,
        timeout_seconds=settings.here.request_timeout_seconds,
    )
    segments = TrafficParser((lat, lon)).parse(fetcher.fetch())
    if not segments:
        raise ValueError("HERE returned no traffic segments for the requested area.")

    center = (lat, lon)
    if geo:
        near = segments_near_center(segments, center)
        selected = select_main_road_segment(near, center)
    else:
        roads = group_by_road(segments)
        for index, road in enumerate(roads, start=1):
            print(
                f"{index:>3}  {road.name[:38]:<38} {len(road.segments):>4}  "
                f"{road.average_speed_kmh:>7.1f} km/h  "
                f"jam={road.average_jam_factor:>4.1f}"
            )
        chosen = choose_road_interactively(roads, input_reader=input_reader)
        selected = representative_segment(chosen.segments, center)

    state, selected = build_map_state_for_road(
        segment=selected,
        radius_meters=radius_meters,
        map_name=map_name,
        project_paths=settings.paths,
    )
    provisioning = build_map_provisioning_service(settings).provision(state)
    profile = provisioning.state.to_profile(settings.paths)
    readings = tuple(SyntheticDeviceProvider(profile.device_registry).poll())

    return BaselineProposal(
        state=provisioning.state,
        segment=selected,
        provisioning=provisioning,
        device_readings=readings,
        estimated_vehicle_count=derive_target_vehicle_count(readings),
    )


def build_map_provisioning_service(settings: AppSettings) -> MapProvisioningService:
    """The exact concrete provisioning service ``motion map provision`` uses."""

    from motion.config.runtime_state import ActiveMapStateRepository
    from motion.infrastructure.maps.artifacts import LocalMapArtifactProcessor
    from motion.infrastructure.maps.converter import CarlaOsmToOpenDriveConverter
    from motion.infrastructure.osm.downloader import OsmDownloader

    return MapProvisioningService(
        downloader=OsmDownloader(
            endpoints=settings.osm.endpoints,
            contact_email=settings.osm.contact_email,
            timeout_seconds=settings.osm.request_timeout_seconds,
        ),
        converter=CarlaOsmToOpenDriveConverter(),
        artifact_processor=LocalMapArtifactProcessor(),
        state_repository=ActiveMapStateRepository(settings.paths.active_map_state),
        project_root=settings.paths.root,
    )


def stage_editable_copy(
    profile: MapProfile, scenario_id: str, paths: ProjectPaths
) -> tuple[Path, str]:
    """Copy the baseline OSM to an editable, scenario-named sibling map.

    The variant lives at ``data/maps/<baseline>__scenario-<id>/...`` -- the
    same ``data/maps/<name>/`` convention as any other map, just named for the
    scenario -- and is never written to ``active_map.json``. Returns the
    editable path and its SHA-256 at staging time, so ``apply`` can detect
    whether the operator actually changed anything before converting it.
    """

    variant_name = paths.scenario_map_name(profile.name, scenario_id)
    editable_path = paths.map_osm_path(variant_name)
    editable_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(profile.osm_path, editable_path)
    return editable_path, sha256_of(editable_path)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_scenario_id(*, clock: Callable[[], float] = time.time) -> str:
    """A short, filesystem-safe, effectively-unique scenario id."""

    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(clock()))
    return f"{timestamp}-{uuid.uuid4().hex[:6]}"


class ScenarioMapConverter:
    """Convert and repair an already-edited OSM file into OpenDRIVE.

    Reuses the exact ports ``MapProvisioningService`` uses for UC-01's own
    baseline provisioning (``MapConverter``, ``MapArtifactProcessor``), but
    never downloads -- the input OSM was already staged and edited externally
    -- and never commits to the shared active-map state.
    """

    def __init__(
        self,
        *,
        converter: MapConverter,
        artifact_processor: MapArtifactProcessor,
    ) -> None:
        self._converter = converter
        self._artifact_processor = artifact_processor

    def convert_and_repair(self, profile: MapProfile) -> MapArtifactProcessingResult:
        self._converter.convert(profile)
        return self._artifact_processor.repair_and_validate(profile.xodr_path)


def build_scenario_map_converter() -> ScenarioMapConverter:
    from motion.infrastructure.maps.artifacts import LocalMapArtifactProcessor
    from motion.infrastructure.maps.converter import CarlaOsmToOpenDriveConverter

    return ScenarioMapConverter(
        converter=CarlaOsmToOpenDriveConverter(),
        artifact_processor=LocalMapArtifactProcessor(),
    )


class FrozenTrafficProvider:
    """Replay a fixed, already-fetched segment snapshot on every call.

    Used so the baseline KPI snapshot and the modified-map simulation react
    to identical real traffic conditions instead of two independent live
    fetches that could disagree -- fetch once, replay twice. This is a
    deliberate fairness choice, documented in docs/scenario-kpis.md.
    """

    def __init__(self, segments: Sequence[TrafficSegment]) -> None:
        self._segments = list(segments)

    def fetch_segments(self) -> list[TrafficSegment]:
        return list(self._segments)


def as_traffic_provider(segments: Sequence[TrafficSegment]) -> TrafficDataProvider:
    return FrozenTrafficProvider(segments)
