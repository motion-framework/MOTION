"""Versioned, atomic persistence for generated map/session state."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traffic_mirror.domain.geography import BoundingBox
from traffic_mirror.domain.maps import MapProfile

from .paths import ProjectPaths, validate_map_name
from .settings import load_environment_values

RUNTIME_STATE_SCHEMA_VERSION = 1


class RuntimeStateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ActiveMapState:
    name: str
    bbox: BoundingBox
    osm_path: str
    xodr_path: str
    device_registry: dict[str, tuple[float, float]]
    road_filter: str = ""
    geo_filter: bool = False
    anchor_functional_class: int | None = None
    source: str = "provisioned"
    created_at_utc: str = ""

    def to_profile(self, project_paths: ProjectPaths) -> MapProfile:
        def resolved(path_text: str) -> Path:
            path = Path(path_text)
            candidate = (path if path.is_absolute() else project_paths.root / path).resolve()
            try:
                candidate.relative_to(project_paths.root.resolve())
            except ValueError as error:
                raise RuntimeStateError(
                    f"Active-map path escapes the project root: {path_text!r}"
                ) from error
            return candidate

        return MapProfile(
            name=self.name,
            bbox=self.bbox,
            osm_path=resolved(self.osm_path),
            xodr_path=resolved(self.xodr_path),
            device_registry=dict(self.device_registry),
        )

    @classmethod
    def for_new_map(
        cls,
        *,
        name: str,
        bbox: BoundingBox,
        project_paths: ProjectPaths,
        device_registry: Mapping[str, tuple[float, float]] | None = None,
        road_filter: str = "",
        geo_filter: bool = False,
        anchor_functional_class: int | None = None,
        source: str = "provisioned",
    ) -> ActiveMapState:
        validate_map_name(name)
        return cls(
            name=name,
            bbox=bbox,
            osm_path=str(project_paths.map_osm_path(name).relative_to(project_paths.root)),
            xodr_path=str(project_paths.map_xodr_path(name).relative_to(project_paths.root)),
            device_registry=dict(device_registry or {}),
            road_filter=road_filter,
            geo_filter=geo_filter,
            anchor_functional_class=anchor_functional_class,
            source=source,
            created_at_utc=datetime.now(UTC).isoformat(),
        )


class ActiveMapStateRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, state: ActiveMapState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": RUNTIME_STATE_SCHEMA_VERSION,
            **asdict(state),
        }
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, self.path)

    def load(self) -> ActiveMapState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise RuntimeStateError(f"Active map state not found: {self.path}") from error
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeStateError(f"Cannot read active map state: {self.path}") from error
        return _state_from_payload(payload)


def _state_from_payload(payload: Any) -> ActiveMapState:
    if not isinstance(payload, dict):
        raise RuntimeStateError("Active map state must be a JSON object")
    if payload.get("schema_version") != RUNTIME_STATE_SCHEMA_VERSION:
        raise RuntimeStateError("Unsupported active map state schema version")
    try:
        bbox_payload = payload["bbox"]
        registry = {
            str(device_id): (float(coords[0]), float(coords[1]))
            for device_id, coords in payload.get("device_registry", {}).items()
        }
        state = ActiveMapState(
            name=validate_map_name(str(payload["name"])),
            bbox=BoundingBox(**bbox_payload),
            osm_path=str(payload["osm_path"]),
            xodr_path=str(payload["xodr_path"]),
            device_registry=registry,
            road_filter=str(payload.get("road_filter", "")),
            geo_filter=bool(payload.get("geo_filter", False)),
            anchor_functional_class=(
                int(payload["anchor_functional_class"])
                if payload.get("anchor_functional_class") is not None
                else None
            ),
            source=str(payload.get("source", "provisioned")),
            created_at_utc=str(payload.get("created_at_utc", "")),
        )
    except (AttributeError, KeyError, TypeError, ValueError, IndexError) as error:
        raise RuntimeStateError("Invalid active map state") from error
    return state


def load_active_map_state(
    *,
    paths: ProjectPaths,
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ActiveMapState:
    repository = ActiveMapStateRepository(paths.active_map_state)
    if repository.path.is_file():
        return repository.load()
    return legacy_state_from_environment(
        load_environment_values(paths=paths, env_file=env_file, environ=environ),
        paths,
    )


def legacy_state_from_environment(values: Mapping[str, str], paths: ProjectPaths) -> ActiveMapState:
    """Read, but never write, the former `.env` runtime-state representation."""

    required = ("MAP_SW_LAT", "MAP_SW_LON", "MAP_NE_LAT", "MAP_NE_LON")
    if not all(values.get(name) for name in required):
        raise RuntimeStateError(
            "No active map state. Provision a map first or provide the legacy "
            "MAP_SW_*/MAP_NE_* variables for compatibility."
        )
    name = validate_map_name(values.get("ACTIVE_MAP_NAME", "adhoc_map"))
    try:
        registry_payload = json.loads(values.get("MAP_DEVICE_REGISTRY", "{}"))
        registry = {
            str(device_id): (float(coords[0]), float(coords[1]))
            for device_id, coords in registry_payload.items()
        }
        anchor_text = values.get("MIRROR_ANCHOR_FC", "").strip()
        return ActiveMapState(
            name=name,
            bbox=BoundingBox(
                south_west_lat=float(values["MAP_SW_LAT"]),
                south_west_lon=float(values["MAP_SW_LON"]),
                north_east_lat=float(values["MAP_NE_LAT"]),
                north_east_lon=float(values["MAP_NE_LON"]),
            ),
            osm_path=values.get(
                "MAP_OSM_PATH", str(paths.map_osm_path(name).relative_to(paths.root))
            ),
            xodr_path=values.get(
                "MAP_XODR_PATH", str(paths.map_xodr_path(name).relative_to(paths.root))
            ),
            device_registry=registry,
            road_filter=values.get("MIRROR_ROAD_FILTER", ""),
            geo_filter=values.get("MIRROR_GEO_FILTER", "") == "1",
            anchor_functional_class=int(anchor_text) if anchor_text else None,
            source="legacy-env",
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
        KeyError,
        IndexError,
        json.JSONDecodeError,
    ) as error:
        raise RuntimeStateError("Invalid legacy map state in environment") from error
