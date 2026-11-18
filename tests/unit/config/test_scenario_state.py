from __future__ import annotations

import json

import pytest

from motion.config.paths import ProjectPaths, UnsafeScenarioIdError
from motion.config.runtime_state import ActiveMapState
from motion.config.scenario_state import (
    ScenarioRecord,
    ScenarioStateError,
    ScenarioStateRepository,
)
from motion.domain.geography import BoundingBox
from motion.domain.scenarios import ScenarioModification, ScenarioStatus


def _baseline_state(paths: ProjectPaths) -> ActiveMapState:
    return ActiveMapState.for_new_map(
        name="salerno",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        project_paths=paths,
        device_registry={"D1": (40.005, 14.005)},
    )


def _record(paths: ProjectPaths) -> ScenarioRecord:
    return ScenarioRecord.for_new_scenario(
        scenario_id="20260101-000000-abcdef",
        use_case_id="UC-02",
        modification=ScenarioModification(kind="LANE_CLOSURE", notes="test"),
        baseline_state=_baseline_state(paths),
        variant_map_name="salerno__scenario-20260101-000000-abcdef",
        editable_osm_path="data/maps/salerno__scenario-20260101-000000-abcdef/x.osm",
        editable_osm_sha256="0" * 64,
    )


def test_scenario_record_round_trip_is_versioned_and_atomic(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    record = _record(paths)
    repository = ScenarioStateRepository(paths.scenarios)

    repository.save(record)

    assert repository.load(record.scenario_id) == record
    payload = json.loads(repository.path_for(record.scenario_id).read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["status"] == "STAGED"
    assert payload["baseline_state"]["name"] == "salerno"
    assert not repository.path_for(record.scenario_id).with_suffix(".json.tmp").exists()


def test_scenario_record_survives_status_and_kpi_report_updates(tmp_path) -> None:
    from dataclasses import replace

    paths = ProjectPaths.discover(tmp_path)
    repository = ScenarioStateRepository(paths.scenarios)
    record = _record(paths)
    repository.save(record)

    updated = replace(
        record,
        status=ScenarioStatus.SIMULATED,
        kpi_report={"delta": {"travel_time_seconds": 4.5}},
        heatmap_path="outputs/scenarios/x_heatmap.png",
    )
    repository.save(updated)

    reloaded = repository.load(record.scenario_id)
    assert reloaded.status is ScenarioStatus.SIMULATED
    assert reloaded.kpi_report == {"delta": {"travel_time_seconds": 4.5}}
    assert reloaded.heatmap_path == "outputs/scenarios/x_heatmap.png"


def test_missing_scenario_is_reported_as_a_domain_error(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    repository = ScenarioStateRepository(paths.scenarios)

    with pytest.raises(ScenarioStateError, match="not found"):
        repository.load("does-not-exist")


def test_malformed_scenario_state_is_reported_as_a_domain_error(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    repository = ScenarioStateRepository(paths.scenarios)
    path = repository.path_for("broken")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": 1, "scenario_id": "broken"}), encoding="utf-8")

    with pytest.raises(ScenarioStateError, match="Invalid scenario state"):
        repository.load("broken")


def test_unsupported_schema_version_is_rejected(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    repository = ScenarioStateRepository(paths.scenarios)
    path = repository.path_for("future")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")

    with pytest.raises(ScenarioStateError, match="Unsupported scenario state schema version"):
        repository.load("future")


def test_scenario_id_cannot_escape_the_managed_directory(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    repository = ScenarioStateRepository(paths.scenarios)

    with pytest.raises(UnsafeScenarioIdError):
        repository.path_for("../escape")
