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
    assert payload[0]["status"] == "IMPLEMENTED"
    assert all(entry["status"] == "NOT IMPLEMENTED / RESEARCH DIRECTION" for entry in payload[1:])


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
