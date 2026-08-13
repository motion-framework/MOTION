"""Load static configuration once near the CLI composition root."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .paths import ProjectPaths

DEFAULT_HERE_FLOW_URL = "https://data.traffic.hereapi.com/v7/flow"
DEFAULT_HERE_INCIDENTS_URL = "https://data.traffic.hereapi.com/v7/incidents"
DEFAULT_OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/map",
    "https://overpass.kumi.systems/api/map",
    "https://overpass.private.coffee/api/map",
)


class SettingsError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CarlaSettings:
    host: str = "localhost"
    rpc_port: int = 2_000
    traffic_manager_port: int = 8_000
    client_timeout_seconds: float = 120.0
    executable_path: Path | None = None


@dataclass(frozen=True, slots=True)
class HereSettings:
    api_key: str = ""
    flow_url: str = DEFAULT_HERE_FLOW_URL
    incidents_url: str = DEFAULT_HERE_INCIDENTS_URL
    request_timeout_seconds: float = 10.0
    archive_mode: str = "off"


@dataclass(frozen=True, slots=True)
class OsmSettings:
    contact_email: str = ""
    endpoints: tuple[str, ...] = DEFAULT_OVERPASS_ENDPOINTS
    request_timeout_seconds: float = 180.0


@dataclass(frozen=True, slots=True)
class MirrorSettings:
    update_interval_seconds: float = 60.0
    road_filter: str = ""
    geo_filter: bool = False
    anchor_functional_class: int | None = None


@dataclass(frozen=True, slots=True)
class AppSettings:
    paths: ProjectPaths
    carla: CarlaSettings
    here: HereSettings
    osm: OsmSettings
    mirror: MirrorSettings


def read_dotenv(path: Path) -> dict[str, str]:
    """Read the conservative KEY=VALUE subset used by this project."""

    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def load_environment_values(
    *,
    paths: ProjectPaths,
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    values = read_dotenv(env_file or paths.root / ".env")
    values.update(dict(os.environ if environ is None else environ))
    return values


def _integer(values: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(values.get(name, str(default)))
    except ValueError as error:
        raise SettingsError(f"{name} must be an integer") from error


def _floating(values: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(values.get(name, str(default)))
    except ValueError as error:
        raise SettingsError(f"{name} must be a number") from error


def _positive_floating(values: Mapping[str, str], name: str, default: float) -> float:
    value = _floating(values, name, default)
    if value <= 0:
        raise SettingsError(f"{name} must be positive")
    return value


def _port(values: Mapping[str, str], name: str, default: int) -> int:
    value = _integer(values, name, default)
    if not 1 <= value <= 65_535:
        raise SettingsError(f"{name} must be between 1 and 65535")
    return value


def _boolean(values: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = values.get(name, "1" if default else "0").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    raise SettingsError(f"{name} must be a boolean value")


def load_settings(
    *,
    root: Path | None = None,
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> AppSettings:
    process_values = os.environ if environ is None else environ
    paths = ProjectPaths.discover(root)
    values = load_environment_values(
        paths=paths,
        env_file=env_file,
        environ=process_values,
    )
    configured_root = values.get("TRAFFIC_MIRROR_PROJECT_ROOT", "").strip()
    if root is None and configured_root:
        paths = ProjectPaths.discover(Path(configured_root).expanduser())
        values = load_environment_values(
            paths=paths,
            env_file=env_file,
            environ=process_values,
        )

    executable_text = values.get("CARLA_EXECUTABLE_PATH", "").strip()
    archive_mode = values.get("HERE_ARCHIVE_MODE", "off").strip().lower()
    if archive_mode not in {"off", "record"}:
        raise SettingsError("HERE_ARCHIVE_MODE must be 'off' or 'record'")

    anchor_text = values.get("MIRROR_ANCHOR_FC", "").strip()
    try:
        anchor_fc = int(anchor_text) if anchor_text else None
    except ValueError as error:
        raise SettingsError("MIRROR_ANCHOR_FC must be an integer") from error

    endpoints_text = values.get("OSM_OVERPASS_ENDPOINTS", "").strip()
    osm_endpoints = (
        tuple(item.strip() for item in endpoints_text.split(",") if item.strip())
        if endpoints_text
        else DEFAULT_OVERPASS_ENDPOINTS
    )
    if not osm_endpoints:
        raise SettingsError("At least one Overpass endpoint must be configured")

    return AppSettings(
        paths=paths,
        carla=CarlaSettings(
            host=values.get("CARLA_HOST", "localhost"),
            rpc_port=_port(values, "CARLA_PORT", 2_000),
            traffic_manager_port=_port(values, "CARLA_TRAFFIC_MANAGER_PORT", 8_000),
            client_timeout_seconds=_positive_floating(
                values, "CARLA_CLIENT_TIMEOUT_SECONDS", 120.0
            ),
            executable_path=Path(executable_text).expanduser() if executable_text else None,
        ),
        here=HereSettings(
            api_key=values.get("HERE_API_KEY", ""),
            flow_url=values.get("HERE_FLOW_URL", DEFAULT_HERE_FLOW_URL),
            incidents_url=values.get("HERE_INCIDENTS_URL", DEFAULT_HERE_INCIDENTS_URL),
            request_timeout_seconds=_positive_floating(
                values, "HERE_REQUEST_TIMEOUT_SECONDS", 10.0
            ),
            archive_mode=archive_mode,
        ),
        osm=OsmSettings(
            contact_email=values.get("OSM_DOWNLOADER_CONTACT_EMAIL", ""),
            endpoints=osm_endpoints,
            request_timeout_seconds=_positive_floating(
                values, "OSM_REQUEST_TIMEOUT_SECONDS", 180.0
            ),
        ),
        mirror=MirrorSettings(
            update_interval_seconds=_positive_floating(
                values, "MIRROR_UPDATE_INTERVAL_SECONDS", 60.0
            ),
            road_filter=values.get("MIRROR_ROAD_FILTER", ""),
            geo_filter=_boolean(values, "MIRROR_GEO_FILTER"),
            anchor_functional_class=anchor_fc,
        ),
    )
