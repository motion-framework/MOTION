"""Application service for UC-03 infrastructure event simulation.

``stage`` -> (external edit) -> ``apply`` -> ``simulate``, the same shape as
UC-02 -- both call the shared ``application.scenario_workflow`` -- but
``simulate`` also assembles and renders a before/after congestion heatmap.
See the package README for the exact CLI flow.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
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
from motion.domain.heatmap import CongestionHeatmap, build_congestion_heatmap
from motion.domain.kpi import (
    DEFAULT_GRAMS_CO2_PER_VEHICLE_KM,
    KpiDelta,
    KpiSnapshot,
    snapshot_from_measured,
    snapshot_from_segments,
)
from motion.domain.mirroring import MAXIMUM_VEHICLE_COUNT, SpeedMirrorPolicy
from motion.domain.population import derive_population_targets
from motion.domain.scenarios import ScenarioModification, ScenarioStatus, validate_modification_kind
from motion.domain.traffic import TrafficSegment

from .modifications import UC03_MODIFICATION_KINDS

if TYPE_CHECKING:
    from motion.config.paths import ProjectPaths
    from motion.config.settings import AppSettings
    from motion.domain.maps import MapProfile
    from motion.ports.simulator import TrafficSimulator

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InfrastructureSimulationReport:
    scenario_id: str
    baseline: KpiSnapshot
    scenario: KpiSnapshot
    delta: KpiDelta
    ticks_run: int
    heatmap: CongestionHeatmap
    heatmap_image_path: str


class InfrastructureEventService:
    """Stage -> apply -> simulate orchestration for UC-03."""

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
        input_reader: Callable[[str], str] = input,
        scenario_id: str | None = None,
    ) -> ScenarioRecord:
        kind = validate_modification_kind(modification_kind, UC03_MODIFICATION_KINDS)
        modification = ScenarioModification(kind=kind, notes=notes)
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
            use_case_id="UC-03",
            modification=modification,
            baseline_state=proposal.provisioning.state,
            variant_map_name=self._settings.paths.scenario_map_name(profile.name, chosen_id),
            editable_osm_path=str(editable_path.relative_to(self._settings.paths.root)),
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
            variant_xodr_path=str(variant_profile.xodr_path.relative_to(self._settings.paths.root)),
        )
        self._repository.save(updated)
        return updated

    def simulate(
        self,
        scenario_id: str,
        *,
        offline: bool,
        ticks: int = 1,
        grams_per_vehicle_km: float = DEFAULT_GRAMS_CO2_PER_VEHICLE_KM,
        heatmap_output: Path | None = None,
        simulator_factory: Callable[[MapProfile], TrafficSimulator] | None = None,
        renderer: Callable[[CongestionHeatmap, Path, str], Path] | None = None,
    ) -> InfrastructureSimulationReport:
        if ticks <= 0:
            raise ValueError("ticks must be positive.")
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

        projector = _projector_for(variant_profile)
        coverage = MapCoverage(variant_profile, projector)
        heatmap = _congestion_heatmap_for(coverage, segments)

        build_simulator = simulator_factory or _default_simulator_factory(self._settings)
        simulator = build_simulator(variant_profile)
        mirror_service = TrafficMirrorService(
            traffic_provider=as_traffic_provider(segments),
            device_provider=SyntheticDeviceProvider(variant_profile.device_registry),
            simulator=simulator,
            coverage=coverage,
            speed_policy=SpeedMirrorPolicy(variant_profile.speed_limit_kmh),
            reporter=NullTickReporter(),
        )
        try:
            mirror_service.prepare()
            for _tick in range(ticks):
                mirror_service.run_tick()
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

        image_path = heatmap_output or self._settings.paths.scenario_outputs / (
            f"{scenario_id}_heatmap.png"
        )
        render = renderer or _default_renderer()
        render(heatmap, image_path, f"UC-03 scenario {scenario_id}")

        report = InfrastructureSimulationReport(
            scenario_id=scenario_id,
            baseline=baseline_kpi,
            scenario=scenario_kpi,
            delta=KpiDelta.between(baseline_kpi, scenario_kpi),
            ticks_run=ticks,
            heatmap=heatmap,
            heatmap_image_path=str(image_path),
        )
        self._repository.save(
            replace(
                record,
                status=ScenarioStatus.SIMULATED,
                kpi_report=_report_to_dict(report),
                heatmap_path=str(image_path),
            )
        )
        return report


def _congestion_heatmap_for(
    coverage: MapCoverage, segments: Sequence[TrafficSegment]
) -> CongestionHeatmap:
    """The same per-segment population-allocation math UC-01's own tick uses.

    Mirrors ``TrafficMirrorService._synchronize_by_segment`` exactly (clip to
    map coverage, resize to the in-map length, then
    ``derive_population_targets``) so the heatmap's "after" figure is
    consistent with what UC-01's own mirroring loop would allocate on this
    map -- a policy prediction, not a per-vehicle CARLA measurement.
    """

    coverages = coverage.coverages_of(coverage.segments_touching_map(segments))
    population_coverages = [coverage.resized_for_population(item) for item in coverages]
    resized_segments = [item.segment for item in population_coverages]
    allocations = derive_population_targets(resized_segments, MAXIMUM_VEHICLE_COUNT)
    return build_congestion_heatmap(resized_segments, allocations)


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


def _default_renderer() -> Callable[[CongestionHeatmap, Path, str], Path]:
    from motion.infrastructure.reporting.heatmap import render_congestion_heatmap

    def render(heatmap: CongestionHeatmap, output_path: Path, title: str) -> Path:
        return render_congestion_heatmap(heatmap, output_path, title=title)

    return render


def _report_to_dict(report: InfrastructureSimulationReport) -> dict[str, Any]:
    return asdict(report)
