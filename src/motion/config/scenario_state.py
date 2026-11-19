"""Versioned, atomic persistence for UC-02/UC-03 scenario records.

Mirrors ``config.runtime_state``'s ``ActiveMapState``/
``ActiveMapStateRepository`` pattern, but as a parallel, per-scenario pointer
file so a scenario's baseline/modified map pair never overwrites UC-01's own
single active-map state (see docs/architecture.md).

The full ``baseline_state`` is embedded (not just its map name) because
``var/runtime/active_map.json`` holds only the single *current* active map:
by the time ``apply``/``simulate`` run, an unrelated ``motion mirror`` call
may already have replaced it. A scenario must remain reconstructable from its
own record alone.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from motion.domain.scenarios import ScenarioModification, ScenarioStatus

from .paths import ProjectPaths, validate_map_name, validate_scenario_id
from .runtime_state import ActiveMapState, active_map_state_from_payload

SCENARIO_STATE_SCHEMA_VERSION = 1


class ScenarioStateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScenarioRecord:
    scenario_id: str
    use_case_id: str
    modification: ScenarioModification
    baseline_state: ActiveMapState
    variant_map_name: str
    editable_osm_path: str
    editable_osm_sha256: str
    status: ScenarioStatus = ScenarioStatus.STAGED
    variant_xodr_path: str = ""
    kpi_report: dict[str, Any] | None = None
    heatmap_path: str = ""
    created_at_utc: str = ""

    @classmethod
    def for_new_scenario(
        cls,
        *,
        scenario_id: str,
        use_case_id: str,
        modification: ScenarioModification,
        baseline_state: ActiveMapState,
        variant_map_name: str,
        editable_osm_path: str,
        editable_osm_sha256: str,
    ) -> ScenarioRecord:
        return cls(
            scenario_id=validate_scenario_id(scenario_id),
            use_case_id=use_case_id,
            modification=modification,
            baseline_state=baseline_state,
            variant_map_name=validate_map_name(variant_map_name),
            editable_osm_path=editable_osm_path,
            editable_osm_sha256=editable_osm_sha256,
            created_at_utc=datetime.now(UTC).isoformat(),
        )


class ScenarioStateRepository:
    """Atomic JSON persistence for one scenario record per file."""

    def __init__(self, scenarios_root: Path) -> None:
        self.scenarios_root = scenarios_root

    def path_for(self, scenario_id: str) -> Path:
        return self.scenarios_root / f"{validate_scenario_id(scenario_id)}.json"

    def save(self, record: ScenarioRecord) -> None:
        path = self.path_for(record.scenario_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCENARIO_STATE_SCHEMA_VERSION,
            **asdict(record),
        }
        # dataclasses.asdict already recurses into ``modification`` and
        # ``baseline_state`` (including its nested ``BoundingBox``); only the
        # StrEnum needs an explicit, unambiguous string conversion here.
        payload["status"] = record.status.value
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)

    def load(self, scenario_id: str) -> ScenarioRecord:
        path = self.path_for(scenario_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ScenarioStateError(f"Scenario not found: {scenario_id}") from error
        except (OSError, json.JSONDecodeError) as error:
            raise ScenarioStateError(f"Cannot read scenario state: {path}") from error
        return _record_from_payload(payload)


def _record_from_payload(payload: Any) -> ScenarioRecord:
    if not isinstance(payload, dict):
        raise ScenarioStateError("Scenario state must be a JSON object")
    if payload.get("schema_version") != SCENARIO_STATE_SCHEMA_VERSION:
        raise ScenarioStateError("Unsupported scenario state schema version")
    try:
        modification_payload = payload["modification"]
        modification = ScenarioModification(
            kind=str(modification_payload["kind"]),
            notes=str(modification_payload.get("notes", "")),
            modified_speed_limit_kmh=(
                float(modification_payload["modified_speed_limit_kmh"])
                if modification_payload.get("modified_speed_limit_kmh") is not None
                else None
            ),
        )
        baseline_state = active_map_state_from_payload(payload["baseline_state"])
        return ScenarioRecord(
            scenario_id=validate_scenario_id(str(payload["scenario_id"])),
            use_case_id=str(payload["use_case_id"]),
            modification=modification,
            baseline_state=baseline_state,
            variant_map_name=validate_map_name(str(payload["variant_map_name"])),
            editable_osm_path=str(payload["editable_osm_path"]),
            editable_osm_sha256=str(payload["editable_osm_sha256"]),
            status=ScenarioStatus(str(payload.get("status", ScenarioStatus.STAGED.value))),
            variant_xodr_path=str(payload.get("variant_xodr_path", "")),
            kpi_report=payload.get("kpi_report"),
            heatmap_path=str(payload.get("heatmap_path", "")),
            created_at_utc=str(payload.get("created_at_utc", "")),
        )
    except (AttributeError, KeyError, TypeError, ValueError, IndexError) as error:
        raise ScenarioStateError("Invalid scenario state") from error


def scenario_state_repository(paths: ProjectPaths) -> ScenarioStateRepository:
    return ScenarioStateRepository(paths.scenarios)
