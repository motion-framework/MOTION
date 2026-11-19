"""Project path resolution independent of the process working directory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SAFE_MAP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class UnsafeMapNameError(ValueError):
    pass


class UnsafeScenarioIdError(ValueError):
    pass


def validate_map_name(name: str) -> str:
    if name in {".", ".."} or not SAFE_MAP_NAME.fullmatch(name):
        raise UnsafeMapNameError(
            "Map names must start with an alphanumeric character and contain "
            "only letters, digits, '.', '_' or '-'."
        )
    return name


def validate_scenario_id(scenario_id: str) -> str:
    """Apply the same safe-filename constraint used for map names.

    Scenario ids are used both as a filename component
    (``var/runtime/scenarios/<id>.json``) and, embedded in a map name
    (``<baseline>__scenario-<id>``), so they must satisfy the stricter of the
    two constraints, which is exactly ``SAFE_MAP_NAME``.
    """

    if scenario_id in {".", ".."} or not SAFE_MAP_NAME.fullmatch(scenario_id):
        raise UnsafeScenarioIdError(
            "Scenario ids must start with an alphanumeric character and contain "
            "only letters, digits, '.', '_' or '-'."
        )
    return scenario_id


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    root: Path

    @classmethod
    def discover(cls, root: Path | None = None) -> ProjectPaths:
        if root is not None:
            return cls(root.resolve())
        source_candidate = Path(__file__).resolve().parents[3]
        discovered = (
            source_candidate if (source_candidate / "pyproject.toml").is_file() else Path.cwd()
        )
        return cls(discovered.resolve())

    @property
    def maps(self) -> Path:
        return self.root / "data" / "maps"

    @property
    def runtime(self) -> Path:
        return self.root / "var" / "runtime"

    @property
    def active_map_state(self) -> Path:
        return self.runtime / "active_map.json"

    @property
    def telemetry(self) -> Path:
        return self.root / "data" / "telemetry"

    @property
    def here_archives(self) -> Path:
        return self.root / "artifacts" / "here"

    @property
    def models(self) -> Path:
        return self.root / "artifacts" / "models"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    @property
    def scenarios(self) -> Path:
        return self.runtime / "scenarios"

    @property
    def scenario_outputs(self) -> Path:
        return self.outputs / "scenarios"

    def scenario_state_path(self, scenario_id: str) -> Path:
        return self.scenarios / f"{validate_scenario_id(scenario_id)}.json"

    def scenario_map_name(self, baseline_name: str, scenario_id: str) -> str:
        return validate_map_name(
            f"{validate_map_name(baseline_name)}__scenario-{validate_scenario_id(scenario_id)}"
        )

    def map_directory(self, name: str) -> Path:
        return self.maps / validate_map_name(name)

    def map_osm_path(self, name: str) -> Path:
        safe_name = validate_map_name(name)
        return self.map_directory(safe_name) / f"{safe_name}.osm"

    def map_xodr_path(self, name: str) -> Path:
        safe_name = validate_map_name(name)
        return self.map_directory(safe_name) / f"{safe_name}_map.xodr"
