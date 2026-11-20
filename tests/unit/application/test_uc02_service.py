from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from motion.application.map_provisioning import ProvisioningResult
from motion.application.scenario_workflow import BaselineProposal
from motion.application.use_cases.uc02_what_if_scenario import service as uc02_service
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


def _stage(
    tmp_path,
    monkeypatch,
    *,
    modification_kind: str = "LANE_CLOSURE",
    modified_speed_limit_kmh: float | None = None,
):
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
    monkeypatch.setattr(uc02_service, "propose_and_provision_baseline", lambda **_kwargs: proposal)

    record = uc02_service.WhatIfScenarioService(settings=settings).stage(
        lat=40.0,
        lon=14.0,
        radius_meters=200.0,
        map_name="salerno",
        geo=True,
        modification_kind=modification_kind,
        modified_speed_limit_kmh=modified_speed_limit_kmh,
        scenario_id="sid-1",
    )
    return settings, record


def _ready_record(tmp_path, monkeypatch):
    settings, record = _stage(tmp_path, monkeypatch)
    editable_path = settings.paths.root / record.editable_osm_path
    editable_path.write_text(EDITED_OSM, encoding="utf-8")
    ready = replace(record, status=ScenarioStatus.READY)
    ScenarioStateRepository(settings.paths.scenarios).save(ready)
    return settings, ready


def test_stage_persists_a_scenario_record_and_editable_copy(tmp_path, monkeypatch) -> None:
    settings, record = _stage(tmp_path, monkeypatch)

    assert record.status is ScenarioStatus.STAGED
    assert record.use_case_id == "UC-02"
    assert record.modification.kind == "LANE_CLOSURE"
    editable_path = settings.paths.root / record.editable_osm_path
    assert editable_path.read_text(encoding="utf-8") == MINIMAL_OSM
    reloaded = ScenarioStateRepository(settings.paths.scenarios).load(record.scenario_id)
    assert reloaded == record


def test_stage_records_the_speed_limit_override(tmp_path, monkeypatch) -> None:
    _settings, record = _stage(
        tmp_path,
        monkeypatch,
        modification_kind="SPEED_LIMIT_CHANGE",
        modified_speed_limit_kmh=30.0,
    )

    assert record.modification.kind == "SPEED_LIMIT_CHANGE"
    assert record.modification.modified_speed_limit_kmh == 30.0


def test_stage_rejects_an_unknown_modification_kind(tmp_path, monkeypatch) -> None:
    with pytest.raises(ScenarioValidationError):
        _stage(tmp_path, monkeypatch, modification_kind="NOT_A_REAL_KIND")


def test_apply_requires_staged_status(tmp_path, monkeypatch) -> None:
    settings, record = _stage(tmp_path, monkeypatch)
    ScenarioStateRepository(settings.paths.scenarios).save(
        replace(record, status=ScenarioStatus.READY)
    )

    with pytest.raises(ScenarioStateError, match="not staged"):
        uc02_service.WhatIfScenarioService(settings=settings).apply(record.scenario_id)


def test_apply_requires_an_actual_edit(tmp_path, monkeypatch) -> None:
    settings, record = _stage(tmp_path, monkeypatch)

    with pytest.raises(ScenarioStateError, match="No edit detected"):
        uc02_service.WhatIfScenarioService(settings=settings).apply(record.scenario_id)


def test_apply_converts_the_edited_map_and_marks_ready(tmp_path, monkeypatch) -> None:
    settings, record = _stage(tmp_path, monkeypatch)
    editable_path = settings.paths.root / record.editable_osm_path
    editable_path.write_text(EDITED_OSM, encoding="utf-8")
    converted_profiles = []

    class FakeConverter:
        def convert_and_repair(self, profile):
            converted_profiles.append(profile.name)
            return MapArtifactProcessingResult(
                MapRepairOutcome(0, None), MapRepairOutcome(0, None), 0, 0
            )

    monkeypatch.setattr(uc02_service, "build_scenario_map_converter", lambda: FakeConverter())

    updated = uc02_service.WhatIfScenarioService(settings=settings).apply(record.scenario_id)

    assert updated.status is ScenarioStatus.READY
    assert updated.variant_xodr_path
    assert converted_profiles == [record.variant_map_name]
    reloaded = ScenarioStateRepository(settings.paths.scenarios).load(record.scenario_id)
    assert reloaded.status is ScenarioStatus.READY


def test_simulate_requires_ready_or_simulated_status(tmp_path, monkeypatch) -> None:
    settings, record = _stage(tmp_path, monkeypatch)

    with pytest.raises(ScenarioStateError, match="not ready to simulate"):
        uc02_service.WhatIfScenarioService(settings=settings).simulate(
            record.scenario_id, offline=True
        )


def test_simulate_rejects_non_positive_ticks(tmp_path, monkeypatch) -> None:
    settings, record = _ready_record(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="ticks must be positive"):
        uc02_service.WhatIfScenarioService(settings=settings).simulate(
            record.scenario_id, offline=True, ticks=0
        )


def test_simulate_reports_measured_kpi_delta_and_persists_it(tmp_path, monkeypatch) -> None:
    settings, record = _ready_record(tmp_path, monkeypatch)
    here_segment = segment(length_m=1000.0, speed_kmh=36.0, jam_factor=4.0)
    monkeypatch.setattr(
        uc02_service,
        "build_traffic_provider",
        lambda **_kwargs: FakeTrafficProvider([here_segment]),
    )
    fake_simulator = FakeSimulator(average_speed_kmh=18.0)

    report = uc02_service.WhatIfScenarioService(settings=settings).simulate(
        record.scenario_id,
        offline=True,
        ticks=2,
        simulator_factory=lambda _profile: fake_simulator,
    )

    assert report.ticks_run == 2
    assert report.baseline == snapshot_from_segments([here_segment])
    assert report.scenario == snapshot_from_measured(
        vehicle_count=fake_simulator.vehicle_count,
        average_speed_kmh=18.0,
        distance_km=report.baseline.distance_km,
    )
    assert report.delta == KpiDelta.between(report.baseline, report.scenario)
    tick_calls = [
        call
        for call in fake_simulator.calls
        if call[0] in ("segment_population", "uniform_population")
    ]
    assert len(tick_calls) == 2
    assert fake_simulator.closed is True

    reloaded = ScenarioStateRepository(settings.paths.scenarios).load(record.scenario_id)
    assert reloaded.status is ScenarioStatus.SIMULATED
    assert reloaded.kpi_report is not None
    assert reloaded.kpi_report["scenario_id"] == record.scenario_id


def test_simulate_uses_a_custom_co2_factor(tmp_path, monkeypatch) -> None:
    settings, record = _ready_record(tmp_path, monkeypatch)
    here_segment = segment(length_m=1000.0, speed_kmh=36.0, jam_factor=4.0)
    monkeypatch.setattr(
        uc02_service,
        "build_traffic_provider",
        lambda **_kwargs: FakeTrafficProvider([here_segment]),
    )
    fake_simulator = FakeSimulator(average_speed_kmh=18.0)

    report = uc02_service.WhatIfScenarioService(settings=settings).simulate(
        record.scenario_id,
        offline=True,
        ticks=1,
        grams_per_vehicle_km=1.0,
        simulator_factory=lambda _profile: fake_simulator,
    )

    assert report.baseline == snapshot_from_segments([here_segment], grams_per_vehicle_km=1.0)


def _stage_without_provisioning(tmp_path, monkeypatch, **stage_options):
    """Stage with a provisioning step that must never be reached."""

    def fail_if_provisioned(**_kwargs):
        raise AssertionError("invalid parameters must be rejected before provisioning")

    monkeypatch.setattr(uc02_service, "propose_and_provision_baseline", fail_if_provisioned)
    return uc02_service.WhatIfScenarioService(settings=load_settings(root=tmp_path)).stage(
        lat=40.0,
        lon=14.0,
        radius_meters=200.0,
        map_name="salerno",
        geo=True,
        scenario_id="sid-1",
        **stage_options,
    )


def test_stage_requires_the_new_limit_for_a_speed_limit_change(tmp_path, monkeypatch) -> None:
    with pytest.raises(ScenarioValidationError, match="requires the new limit"):
        _stage_without_provisioning(tmp_path, monkeypatch, modification_kind="SPEED_LIMIT_CHANGE")

    assert not (tmp_path / "var" / "runtime" / "scenarios").exists()


def test_stage_rejects_a_speed_limit_for_any_other_kind(tmp_path, monkeypatch) -> None:
    with pytest.raises(ScenarioValidationError, match="only applies to SPEED_LIMIT_CHANGE"):
        _stage_without_provisioning(
            tmp_path,
            monkeypatch,
            modification_kind="LANE_CLOSURE",
            modified_speed_limit_kmh=30.0,
        )
