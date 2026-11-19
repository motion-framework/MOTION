from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from motion.application.map_provisioning import ProvisioningResult
from motion.application.scenario_workflow import BaselineProposal
from motion.application.use_cases.uc03_infrastructure_event_simulation import (
    service as uc03_service,
)
from motion.config.runtime_state import ActiveMapState
from motion.config.scenario_state import ScenarioStateError, ScenarioStateRepository
from motion.config.settings import load_settings
from motion.domain.geography import BoundingBox
from motion.domain.kpi import KpiDelta, snapshot_from_measured, snapshot_from_segments
from motion.domain.scenarios import ScenarioStatus, ScenarioValidationError
from motion.ports.maps import MapArtifactProcessingResult, MapRepairOutcome
from support.fakes import FakeSimulator, FakeTrafficProvider, segment

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
MINIMAL_OSM = (FIXTURES / "maps" / "minimal.osm").read_text(encoding="utf-8")
EDITED_OSM = MINIMAL_OSM.replace("40.001", "40.0011")

IN_BBOX_SHAPE = ((40.001, 14.001), (40.005, 14.005))


class FakeRenderer:
    def __init__(self):
        self.calls = []

    def __call__(self, heatmap, output_path, title):
        self.calls.append((heatmap, output_path, title))
        return output_path


def _fake_provisioning_result(state: ActiveMapState) -> ProvisioningResult:
    return ProvisioningResult(
        state=state,
        osm_path=Path("unused.osm"),
        xodr_path=Path("unused.xodr"),
        reused_osm=False,
        zero_length_repair=MapRepairOutcome(0, None),
        object_overflow_repair=MapRepairOutcome(0, None),
        remaining_degenerate_geometries=0,
        remaining_object_overflows=0,
    )


def _stage(tmp_path, monkeypatch, *, modification_kind: str = "ZTL_EXTENDED"):
    settings = load_settings(root=tmp_path)
    paths = settings.paths
    baseline_state = ActiveMapState.for_new_map(
        name="salerno",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        project_paths=paths,
        device_registry={"D1": (40.005, 14.005)},
    )
    profile = baseline_state.to_profile(paths)
    profile.osm_path.parent.mkdir(parents=True, exist_ok=True)
    profile.osm_path.write_text(MINIMAL_OSM, encoding="utf-8")

    proposal = BaselineProposal(
        state=baseline_state,
        segment=segment(),
        provisioning=_fake_provisioning_result(baseline_state),
        device_readings=(),
        estimated_vehicle_count=40,
    )
    monkeypatch.setattr(uc03_service, "propose_and_provision_baseline", lambda **_kwargs: proposal)

    record = uc03_service.InfrastructureEventService(settings=settings).stage(
        lat=40.0,
        lon=14.0,
        radius_meters=200.0,
        map_name="salerno",
        geo=True,
        modification_kind=modification_kind,
        scenario_id="sid-uc03",
    )
    return settings, record


def _ready_record(tmp_path, monkeypatch):
    settings, record = _stage(tmp_path, monkeypatch)
    editable_path = settings.paths.root / record.editable_osm_path
    editable_path.write_text(EDITED_OSM, encoding="utf-8")
    ready = replace(record, status=ScenarioStatus.READY)
    ScenarioStateRepository(settings.paths.scenarios).save(ready)
    return settings, ready


def test_stage_persists_a_uc03_scenario_record(tmp_path, monkeypatch) -> None:
    settings, record = _stage(tmp_path, monkeypatch)

    assert record.status is ScenarioStatus.STAGED
    assert record.use_case_id == "UC-03"
    assert record.modification.kind == "ZTL_EXTENDED"
    assert record.modification.modified_speed_limit_kmh is None
    reloaded = ScenarioStateRepository(settings.paths.scenarios).load(record.scenario_id)
    assert reloaded == record


def test_stage_rejects_an_unknown_modification_kind(tmp_path, monkeypatch) -> None:
    with pytest.raises(ScenarioValidationError):
        _stage(tmp_path, monkeypatch, modification_kind="LANE_CLOSURE")


def test_apply_requires_an_actual_edit(tmp_path, monkeypatch) -> None:
    settings, record = _stage(tmp_path, monkeypatch)

    with pytest.raises(ScenarioStateError, match="No edit detected"):
        uc03_service.InfrastructureEventService(settings=settings).apply(record.scenario_id)


def test_apply_converts_the_edited_map_and_marks_ready(tmp_path, monkeypatch) -> None:
    settings, record = _stage(tmp_path, monkeypatch)
    editable_path = settings.paths.root / record.editable_osm_path
    editable_path.write_text(EDITED_OSM, encoding="utf-8")

    class FakeConverter:
        def convert_and_repair(self, profile):
            return MapArtifactProcessingResult(
                MapRepairOutcome(0, None), MapRepairOutcome(0, None), 0, 0
            )

    monkeypatch.setattr(uc03_service, "build_scenario_map_converter", lambda: FakeConverter())

    updated = uc03_service.InfrastructureEventService(settings=settings).apply(record.scenario_id)

    assert updated.status is ScenarioStatus.READY
    assert updated.variant_xodr_path


def test_simulate_requires_ready_or_simulated_status(tmp_path, monkeypatch) -> None:
    settings, record = _stage(tmp_path, monkeypatch)

    with pytest.raises(ScenarioStateError, match="not ready to simulate"):
        uc03_service.InfrastructureEventService(settings=settings).simulate(
            record.scenario_id, offline=True
        )


def test_simulate_builds_and_renders_a_congestion_heatmap(tmp_path, monkeypatch) -> None:
    settings, record = _ready_record(tmp_path, monkeypatch)
    here_segment = segment(
        description="Via Salerno",
        length_m=1000.0,
        speed_kmh=36.0,
        jam_factor=4.0,
        shape_points=IN_BBOX_SHAPE,
    )
    monkeypatch.setattr(
        uc03_service,
        "build_traffic_provider",
        lambda **_kwargs: FakeTrafficProvider([here_segment]),
    )
    fake_simulator = FakeSimulator(average_speed_kmh=18.0)
    renderer = FakeRenderer()
    heatmap_output = settings.paths.root / "outputs" / "custom_heatmap.png"

    report = uc03_service.InfrastructureEventService(settings=settings).simulate(
        record.scenario_id,
        offline=True,
        ticks=1,
        heatmap_output=heatmap_output,
        simulator_factory=lambda _profile: fake_simulator,
        renderer=renderer,
    )

    assert len(report.heatmap.cells) == 1
    assert report.heatmap.cells[0].description == "Via Salerno"
    assert report.heatmap.cells[0].before_congestion_index == pytest.approx(4.0)
    assert report.heatmap_image_path == str(heatmap_output)
    assert len(renderer.calls) == 1
    heatmap_argument, path_argument, title_argument = renderer.calls[0]
    assert heatmap_argument == report.heatmap
    assert path_argument == heatmap_output
    assert record.scenario_id in title_argument

    reloaded = ScenarioStateRepository(settings.paths.scenarios).load(record.scenario_id)
    assert reloaded.heatmap_path == str(heatmap_output)
    assert reloaded.status is ScenarioStatus.SIMULATED


def test_simulate_defaults_the_heatmap_output_path(tmp_path, monkeypatch) -> None:
    settings, record = _ready_record(tmp_path, monkeypatch)
    monkeypatch.setattr(
        uc03_service,
        "build_traffic_provider",
        lambda **_kwargs: FakeTrafficProvider([segment(shape_points=IN_BBOX_SHAPE)]),
    )
    renderer = FakeRenderer()

    report = uc03_service.InfrastructureEventService(settings=settings).simulate(
        record.scenario_id,
        offline=True,
        ticks=1,
        simulator_factory=lambda _profile: FakeSimulator(average_speed_kmh=20.0),
        renderer=renderer,
    )

    expected = settings.paths.scenario_outputs / f"{record.scenario_id}_heatmap.png"
    assert report.heatmap_image_path == str(expected)


def test_simulate_reports_measured_corridor_kpi_delta(tmp_path, monkeypatch) -> None:
    settings, record = _ready_record(tmp_path, monkeypatch)
    here_segment = segment(
        length_m=1000.0, speed_kmh=36.0, jam_factor=4.0, shape_points=IN_BBOX_SHAPE
    )
    monkeypatch.setattr(
        uc03_service,
        "build_traffic_provider",
        lambda **_kwargs: FakeTrafficProvider([here_segment]),
    )
    fake_simulator = FakeSimulator(average_speed_kmh=18.0)

    report = uc03_service.InfrastructureEventService(settings=settings).simulate(
        record.scenario_id,
        offline=True,
        ticks=1,
        simulator_factory=lambda _profile: fake_simulator,
        renderer=FakeRenderer(),
    )

    assert report.baseline == snapshot_from_segments([here_segment])
    assert report.scenario == snapshot_from_measured(
        vehicle_count=fake_simulator.vehicle_count,
        average_speed_kmh=18.0,
        distance_km=report.baseline.distance_km,
    )
    assert report.delta == KpiDelta.between(report.baseline, report.scenario)
    assert fake_simulator.closed is True
