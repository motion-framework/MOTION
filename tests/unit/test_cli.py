from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import motion.cli as cli
from motion.cli import build_parser, main
from motion.domain.geography import BoundingBox
from motion.domain.maps import MapProfile

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_cli_uses_the_project_wide_motion_command() -> None:
    assert build_parser().prog == "motion"


def test_uc_status_is_available_without_external_dependencies(capsys) -> None:
    assert main(["uc-status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [entry["id"] for entry in payload] == [
        "UC-01",
        "UC-02",
        "UC-03",
        "UC-04",
        "UC-05",
        "UC-06",
        "UC-07",
    ]
    assert [entry["status"] for entry in payload[:3]] == ["IMPLEMENTED"] * 3
    assert all(entry["status"] == "NOT IMPLEMENTED / RESEARCH DIRECTION" for entry in payload[3:])


def test_map_inspection_and_validation_have_meaningful_exit_codes(capsys) -> None:
    assert main(["map", "inspect", str(FIXTURES / "maps" / "minimal.osm")]) == 0
    assert "nodes=3" in capsys.readouterr().out

    assert main(["map", "validate", str(FIXTURES / "maps" / "defective.xodr")]) == 1
    assert "1 degenerate, 1 overflow" in capsys.readouterr().out


def test_cli_rejects_an_incomplete_provisioning_area(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main(["map", "provision", "--name", "incomplete", "--lat", "40"])
    assert error.value.code == 2
    assert "either --lat/--lon" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("arguments", "handler_name"),
    [
        (["mirror", "--skip-provision", "--once"], "_handle_mirror"),
        (["telemetry", "collect"], "_handle_telemetry_collect"),
        (
            ["dataset", "build", "input.csv", "--output", "output.csv"],
            "_handle_dataset_build",
        ),
        (["model", "train", "--dataset", "data.csv"], "_handle_model_train"),
        (["model", "infer"], "_handle_model_infer"),
        (["diagnostics", "speed-units"], "_handle_speed_units"),
        (
            [
                "scenario",
                "stage",
                "--lat",
                "40.0",
                "--lon",
                "14.0",
                "--name",
                "salerno",
                "--modification-kind",
                "LANE_CLOSURE",
            ],
            "_handle_scenario_stage",
        ),
        (["scenario", "apply", "sid-1"], "_handle_scenario_apply"),
        (["scenario", "simulate", "sid-1"], "_handle_scenario_simulate"),
        (
            [
                "infra-event",
                "stage",
                "--lat",
                "40.0",
                "--lon",
                "14.0",
                "--name",
                "salerno",
                "--modification-kind",
                "ZTL_EXTENDED",
            ],
            "_handle_infra_event_stage",
        ),
        (["infra-event", "apply", "sid-1"], "_handle_infra_event_apply"),
        (["infra-event", "simulate", "sid-1"], "_handle_infra_event_simulate"),
    ],
)
def test_primary_command_surface_parses(arguments: list[str], handler_name: str) -> None:
    namespace = build_parser().parse_args(arguments)
    assert namespace.handler.__name__ == handler_name


def test_offline_mirror_reuses_active_map_and_reaches_uc01(monkeypatch) -> None:
    args = build_parser().parse_args(["mirror", "--offline", "--once"])
    state = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(cli, "load_active_map_state", lambda **_kwargs: state)

    def fail_if_provisioned(*_args, **_kwargs):
        raise AssertionError("offline mode must not provision through HERE or Overpass")

    monkeypatch.setattr(cli, "_select_and_provision_road", fail_if_provisioned)

    def capture_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "_run_uc01", capture_run)

    settings = SimpleNamespace(paths=object())
    assert cli._handle_mirror(args, settings) == 0
    assert captured["state"] is state
    assert captured["once"] is True
    assert captured["offline"] is True


def test_offline_provider_selection_does_not_build_here(monkeypatch) -> None:
    from motion.infrastructure.here import factory

    here_builder_called = False

    def fail_if_here_is_built(*_args, **_kwargs):
        nonlocal here_builder_called
        here_builder_called = True
        raise AssertionError("HERE provider must not be built in offline mode")

    monkeypatch.setattr(factory, "build_here_provider", fail_if_here_is_built)

    profile = MapProfile(
        name="offline",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        osm_path=Path("map.osm"),
        xodr_path=Path("map.xodr"),
        device_registry={"D1": (40.001, 14.001), "D2": (40.002, 14.002)},
    )
    provider = cli._build_traffic_provider(
        settings=object(),
        profile=profile,
        road_filter="",
        offline=True,
    )

    segments = provider.fetch_segments()
    assert len(segments) == 1
    assert segments[0].description == "Synthetic offline segment 1"
    assert here_builder_called is False


def test_offline_mirror_rejects_provisioning_coordinates() -> None:
    args = build_parser().parse_args(["mirror", "--offline", "--lat", "40.0", "--lon", "14.0"])

    with pytest.raises(ValueError, match="reuses the active map"):
        cli._handle_mirror(args, object())


def _fake_settings() -> SimpleNamespace:
    # WhatIfScenarioService/InfrastructureEventService.__init__ only reads
    # settings.paths.scenarios; everything else in these handler tests is
    # reached through a monkeypatched service method.
    return SimpleNamespace(paths=SimpleNamespace(scenarios=Path("var/runtime/scenarios")))


def _fake_scenario_record(**overrides) -> SimpleNamespace:
    values = {
        "scenario_id": "sid-1",
        "use_case_id": "UC-02",
        "modification": SimpleNamespace(kind="LANE_CLOSURE", notes="close it"),
        "editable_osm_path": "data/maps/salerno__scenario-sid-1/salerno__scenario-sid-1.osm",
        "variant_xodr_path": "data/maps/salerno__scenario-sid-1/salerno__scenario-sid-1_map.xodr",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("module_path", "class_name", "handler_name", "arguments", "use_case_id"),
    [
        (
            "motion.application.use_cases.uc02_what_if_scenario.service",
            "WhatIfScenarioService",
            "_handle_scenario_stage",
            [
                "scenario",
                "stage",
                "--lat",
                "40.0",
                "--lon",
                "14.0",
                "--name",
                "salerno",
                "--modification-kind",
                "LANE_CLOSURE",
                "--geo",
            ],
            "UC-02",
        ),
        (
            "motion.application.use_cases.uc03_infrastructure_event_simulation.service",
            "InfrastructureEventService",
            "_handle_infra_event_stage",
            [
                "infra-event",
                "stage",
                "--lat",
                "40.0",
                "--lon",
                "14.0",
                "--name",
                "salerno",
                "--modification-kind",
                "ZTL_EXTENDED",
                "--geo",
            ],
            "UC-03",
        ),
    ],
)
def test_scenario_stage_handler_calls_the_service_with_parsed_arguments(
    monkeypatch, capsys, module_path, class_name, handler_name, arguments, use_case_id
) -> None:
    module = __import__(module_path, fromlist=[class_name])
    service_class = getattr(module, class_name)
    captured: dict[str, object] = {}

    def fake_stage(self, **kwargs):
        captured.update(kwargs)
        return _fake_scenario_record(use_case_id=use_case_id)

    monkeypatch.setattr(service_class, "stage", fake_stage)

    args = build_parser().parse_args(arguments)
    handler = getattr(cli, handler_name)
    assert handler(args, _fake_settings()) == 0

    assert captured["lat"] == 40.0
    assert captured["lon"] == 14.0
    assert captured["geo"] is True
    assert "sid-1" in capsys.readouterr().out


def test_scenario_apply_handler_calls_the_service(monkeypatch) -> None:
    from motion.application.use_cases.uc02_what_if_scenario.service import WhatIfScenarioService

    captured: dict[str, object] = {}

    def fake_apply(self, scenario_id):
        captured["scenario_id"] = scenario_id
        return _fake_scenario_record()

    monkeypatch.setattr(WhatIfScenarioService, "apply", fake_apply)

    args = build_parser().parse_args(["scenario", "apply", "sid-42"])
    assert cli._handle_scenario_apply(args, _fake_settings()) == 0
    assert captured["scenario_id"] == "sid-42"


def test_scenario_simulate_handler_forwards_ticks_offline_and_co2_override(monkeypatch) -> None:
    from motion.application.use_cases.uc02_what_if_scenario import service as uc02_service
    from motion.domain.kpi import KpiDelta, KpiSnapshot

    captured: dict[str, object] = {}

    def fake_simulate(self, scenario_id, **kwargs):
        captured["scenario_id"] = scenario_id
        captured.update(kwargs)
        zero = KpiSnapshot(0.0, 0.0, 0.0, 0, 0.0)
        return uc02_service.ScenarioSimulationReport(
            scenario_id=scenario_id,
            baseline=zero,
            scenario=zero,
            delta=KpiDelta(0.0, 0.0, 0.0),
            ticks_run=kwargs.get("ticks", 1),
        )

    monkeypatch.setattr(uc02_service.WhatIfScenarioService, "simulate", fake_simulate)

    args = build_parser().parse_args(
        ["scenario", "simulate", "sid-9", "--ticks", "3", "--offline", "--grams-co2-per-km", "50"]
    )
    assert cli._handle_scenario_simulate(args, _fake_settings()) == 0

    assert captured["scenario_id"] == "sid-9"
    assert captured["ticks"] == 3
    assert captured["offline"] is True
    assert captured["grams_per_vehicle_km"] == 50.0


def test_infra_event_simulate_handler_forwards_heatmap_output(monkeypatch, tmp_path) -> None:
    from motion.application.use_cases.uc03_infrastructure_event_simulation import (
        service as uc03_service,
    )
    from motion.domain.heatmap import CongestionHeatmap
    from motion.domain.kpi import KpiDelta, KpiSnapshot

    captured: dict[str, object] = {}
    heatmap_path = tmp_path / "custom.png"

    def fake_simulate(self, scenario_id, **kwargs):
        captured["scenario_id"] = scenario_id
        captured.update(kwargs)
        zero = KpiSnapshot(0.0, 0.0, 0.0, 0, 0.0)
        return uc03_service.InfrastructureSimulationReport(
            scenario_id=scenario_id,
            baseline=zero,
            scenario=zero,
            delta=KpiDelta(0.0, 0.0, 0.0),
            ticks_run=kwargs.get("ticks", 1),
            heatmap=CongestionHeatmap(cells=()),
            heatmap_image_path=str(heatmap_path),
        )

    monkeypatch.setattr(uc03_service.InfrastructureEventService, "simulate", fake_simulate)

    args = build_parser().parse_args(
        ["infra-event", "simulate", "sid-7", "--heatmap-output", str(heatmap_path)]
    )
    assert cli._handle_infra_event_simulate(args, _fake_settings()) == 0

    assert captured["scenario_id"] == "sid-7"
    assert captured["heatmap_output"] == heatmap_path
