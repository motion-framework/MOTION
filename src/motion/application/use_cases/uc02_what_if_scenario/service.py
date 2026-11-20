"""Application service for UC-02 what-if scenario simulation.

``stage`` -> (external edit) -> ``apply`` -> ``simulate``. Reuses UC-01's own
``TrafficMirrorService``/``CarlaTrafficSimulator`` for the modified-map run
instead of driving CARLA ScenarioRunner -- see the package README for why.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any

from motion.application.scenario_workflow import (
    as_traffic_provider,
    build_scenario_map_converter,
    generate_scenario_id,
    propose_and_provision_baseline,
    sha256_of,
    stage_editable_copy,
)
from motion.application.traffic_providers import build_traffic_provider
from motion.application.use_cases.uc01_real_time_traffic_mirroring.coverage import MapCoverage
from motion.application.use_cases.uc01_real_time_traffic_mirroring.reporting import (
    NullTickReporter,
)
from motion.application.use_cases.uc01_real_time_traffic_mirroring.service import (
    TrafficMirrorService,
)
from motion.config.scenario_state import (
    ScenarioRecord,
    ScenarioStateError,
    ScenarioStateRepository,
)
from motion.domain.devices import SyntheticDeviceProvider
from motion.domain.kpi import (
    DEFAULT_GRAMS_CO2_PER_VEHICLE_KM,
    KpiDelta,
    KpiSnapshot,
    snapshot_from_measured,
    snapshot_from_segments,
)
from motion.domain.mirroring import SpeedMirrorPolicy
from motion.domain.scenarios import ScenarioModification, ScenarioStatus, validate_modification_kind

from .modifications import UC02_MODIFICATION_KINDS, validate_uc02_parameters

if TYPE_CHECKING:
    from motion.config.paths import ProjectPaths
    from motion.config.settings import AppSettings
    from motion.domain.maps import MapProfile
    from motion.ports.simulator import TrafficSimulator

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScenarioSimulationReport:
    scenario_id: str
    baseline: KpiSnapshot
    scenario: KpiSnapshot
    delta: KpiDelta
    ticks_run: int


class WhatIfScenarioService:
    """Stage -> apply -> simulate orchestration for UC-02."""

    def __init__(self, *, settings: AppSettings) -> None:
        self._settings = settings
        self._repository = ScenarioStateRepository(settings.paths.scenarios)

    def stage(
        self,
        *,
        lat: float,
        lon: float,
        radius_meters: float,
        map_name: str,
        geo: bool,
        modification_kind: str,
        notes: str = "",
        modified_speed_limit_kmh: float | None = None,
        input_reader: Callable[[str], str] = input,
        scenario_id: str | None = None,
    ) -> ScenarioRecord:
        kind = validate_modification_kind(modification_kind, UC02_MODIFICATION_KINDS)
        validate_uc02_parameters(kind, modified_speed_limit_kmh)
        modification = ScenarioModification(
            kind=kind,
            notes=notes,
            modified_speed_limit_kmh=modified_speed_limit_kmh,
        )
        proposal = propose_and_provision_baseline(
            settings=self._settings,
            lat=lat,
            lon=lon,
            radius_meters=radius_meters,
            map_name=map_name,
            geo=geo,
            input_reader=input_reader,
        )
        chosen_id = scenario_id or generate_scenario_id()
        profile = proposal.provisioning.state.to_profile(self._settings.paths)
        editable_path, digest = stage_editable_copy(profile, chosen_id, self._settings.paths)
        record = ScenarioRecord.for_new_scenario(
            scenario_id=chosen_id,
            use_case_id="UC-02",
            modification=modification,
            baseline_state=proposal.provisioning.state,
            variant_map_name=self._settings.paths.scenario_map_name(profile.name, chosen_id),
            editable_osm_path=editable_path.relative_to(self._settings.paths.root).as_posix(),
            editable_osm_sha256=digest,
        )
        self._repository.save(record)
        return record

    def apply(self, scenario_id: str) -> ScenarioRecord:
        record = self._repository.load(scenario_id)
        if record.status is not ScenarioStatus.STAGED:
            raise ScenarioStateError(
                f"Scenario {scenario_id!r} is not staged (status={record.status.value})."
            )
        editable_path = self._settings.paths.root / record.editable_osm_path
        current_digest = sha256_of(editable_path)
        if current_digest == record.editable_osm_sha256:
            raise ScenarioStateError(
                "No edit detected: the staged OSM file is unchanged since staging. "
                "Edit and save it (e.g. in JOSM) before running apply."
            )
        baseline_profile = record.baseline_state.to_profile(self._settings.paths)
        variant_profile = _variant_profile(record, baseline_profile, self._settings.paths)
        build_scenario_map_converter().convert_and_repair(variant_profile)
        updated = replace(
            record,
            status=ScenarioStatus.READY,
            variant_xodr_path=variant_profile.xodr_path.relative_to(
                self._settings.paths.root
            ).as_posix(),
        )
        self._repository.save(updated)
        return updated

    def simulate(
        self,
        scenario_id: str,
        *,
        offline: bool,
        ticks: int = 1,
        settle_seconds: float = 0.0,
        grams_per_vehicle_km: float = DEFAULT_GRAMS_CO2_PER_VEHICLE_KM,
        simulator_factory: Callable[[MapProfile], TrafficSimulator] | None = None,
    ) -> ScenarioSimulationReport:
        if ticks <= 0:
            raise ValueError("ticks must be positive.")
        if settle_seconds < 0.0:
            raise ValueError("settle_seconds cannot be negative.")
        record = self._repository.load(scenario_id)
        if record.status not in (ScenarioStatus.READY, ScenarioStatus.SIMULATED):
            raise ScenarioStateError(
                f"Scenario {scenario_id!r} is not ready to simulate "
                f"(status={record.status.value}); run apply first."
            )

        baseline_profile = record.baseline_state.to_profile(self._settings.paths)
        variant_profile = _variant_profile(record, baseline_profile, self._settings.paths)

        source_provider = build_traffic_provider(
            settings=self._settings, profile=baseline_profile, road_filter="", offline=offline
        )
        segments = source_provider.fetch_segments()
        baseline_kpi = snapshot_from_segments(segments, grams_per_vehicle_km=grams_per_vehicle_km)

        build_simulator = simulator_factory or _default_simulator_factory(self._settings)
        simulator = build_simulator(variant_profile)
        projector = _projector_for(variant_profile)
        mirror_service = TrafficMirrorService(
            traffic_provider=as_traffic_provider(segments),
            device_provider=SyntheticDeviceProvider(variant_profile.device_registry),
            simulator=simulator,
            coverage=MapCoverage(variant_profile, projector),
            speed_policy=SpeedMirrorPolicy(variant_profile.speed_limit_kmh),
            reporter=NullTickReporter(),
        )
        try:
            mirror_service.prepare()
            for _tick in range(ticks):
                mirror_service.run_tick()
            if settle_seconds > 0.0:
                mirror_service.watch_until(time.monotonic() + settle_seconds)
            vehicle_count = simulator.owned_vehicle_count()
            average_speed_kmh = simulator.average_speed_kmh()
        finally:
            mirror_service.close()

        scenario_kpi = snapshot_from_measured(
            vehicle_count=vehicle_count,
            average_speed_kmh=average_speed_kmh,
            distance_km=baseline_kpi.distance_km,
            grams_per_vehicle_km=grams_per_vehicle_km,
        )
        report = ScenarioSimulationReport(
            scenario_id=scenario_id,
            baseline=baseline_kpi,
            scenario=scenario_kpi,
            delta=KpiDelta.between(baseline_kpi, scenario_kpi),
            ticks_run=ticks,
        )
        self._repository.save(
            replace(record, status=ScenarioStatus.SIMULATED, kpi_report=_report_to_dict(report))
        )
        return report


def _variant_profile(
    record: ScenarioRecord, baseline_profile: MapProfile, paths: ProjectPaths
) -> MapProfile:
    return replace(
        baseline_profile,
        name=record.variant_map_name,
        osm_path=paths.map_osm_path(record.variant_map_name),
        xodr_path=paths.map_xodr_path(record.variant_map_name),
        speed_limit_kmh=(
            record.modification.modified_speed_limit_kmh
            if record.modification.modified_speed_limit_kmh is not None
            else baseline_profile.speed_limit_kmh
        ),
    )


def _projector_for(profile: MapProfile) -> Any:
    from motion.infrastructure.maps.projection import build_geo_transform

    return build_geo_transform(profile.osm_path, profile.proj_string)


def _default_simulator_factory(
    settings: AppSettings,
) -> Callable[[MapProfile], TrafficSimulator]:
    from motion.infrastructure.carla.adapter import CarlaTrafficSimulator

    def factory(profile: MapProfile) -> TrafficSimulator:
        return CarlaTrafficSimulator.from_profile(settings.carla, profile)

    return factory


def _report_to_dict(report: ScenarioSimulationReport) -> dict[str, Any]:
    return asdict(report)
