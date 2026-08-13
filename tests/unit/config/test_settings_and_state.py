from __future__ import annotations

import json

import pytest

from traffic_mirror.config.paths import ProjectPaths, UnsafeMapNameError
from traffic_mirror.config.runtime_state import (
    ActiveMapState,
    ActiveMapStateRepository,
    RuntimeStateError,
    load_active_map_state,
)
from traffic_mirror.config.settings import SettingsError, load_settings
from traffic_mirror.domain.geography import BoundingBox


def test_static_environment_overrides_dotenv(tmp_path) -> None:
    (tmp_path / ".env").write_text("HERE_API_KEY=file-key\nCARLA_PORT=2000\n", encoding="utf-8")
    settings = load_settings(
        root=tmp_path,
        environ={"HERE_API_KEY": "environment-key", "CARLA_PORT": "2001"},
    )
    assert settings.here.api_key == "environment-key"
    assert settings.carla.rpc_port == 2001
    assert settings.carla.client_timeout_seconds == 120.0


def test_project_root_can_be_selected_explicitly_from_configuration(tmp_path) -> None:
    configured_root = tmp_path / "research-run"
    settings = load_settings(environ={"TRAFFIC_MIRROR_PROJECT_ROOT": str(configured_root)})
    assert settings.paths.root == configured_root.resolve()


def test_invalid_settings_are_reported(tmp_path) -> None:
    with pytest.raises(SettingsError, match="CARLA_PORT"):
        load_settings(root=tmp_path, environ={"CARLA_PORT": "not-an-int"})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CARLA_PORT", "0"),
        ("CARLA_TRAFFIC_MANAGER_PORT", "65536"),
        ("CARLA_CLIENT_TIMEOUT_SECONDS", "0"),
        ("HERE_REQUEST_TIMEOUT_SECONDS", "-1"),
        ("OSM_REQUEST_TIMEOUT_SECONDS", "0"),
        ("MIRROR_UPDATE_INTERVAL_SECONDS", "-0.1"),
    ],
)
def test_ports_and_intervals_must_be_usable(tmp_path, name: str, value: str) -> None:
    with pytest.raises(SettingsError, match=name):
        load_settings(root=tmp_path, environ={name: value})


def test_map_name_cannot_escape_managed_directory(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    with pytest.raises(UnsafeMapNameError):
        paths.map_osm_path("../escape")


@pytest.mark.parametrize(
    "bbox",
    [
        (41.0, 14.0, 40.0, 15.0),
        (40.0, 15.0, 41.0, 14.0),
        (-91.0, 14.0, 40.0, 15.0),
        (40.0, 14.0, float("nan"), 15.0),
    ],
)
def test_invalid_bounding_boxes_are_rejected(bbox: tuple[float, ...]) -> None:
    with pytest.raises(ValueError):
        BoundingBox(*bbox)


def test_active_state_round_trip_is_versioned_and_atomic(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    state = ActiveMapState.for_new_map(
        name="test_map",
        bbox=BoundingBox(40, 14, 41, 15),
        project_paths=paths,
        device_registry={"D1": (40.5, 14.5)},
        geo_filter=True,
        anchor_functional_class=3,
    )
    repository = ActiveMapStateRepository(paths.active_map_state)
    repository.save(state)
    assert repository.load() == state
    payload = json.loads(paths.active_map_state.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert not paths.active_map_state.with_suffix(".json.tmp").exists()


def test_malformed_active_state_is_reported_as_a_domain_error(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    paths.active_map_state.parent.mkdir(parents=True)
    paths.active_map_state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "broken",
                "bbox": {
                    "south_west_lat": 40,
                    "south_west_lon": 14,
                    "north_east_lat": 41,
                    "north_east_lon": 15,
                },
                "osm_path": "data/maps/broken.osm",
                "xodr_path": "data/maps/broken.xodr",
                "device_registry": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeStateError, match="Invalid active map state"):
        ActiveMapStateRepository(paths.active_map_state).load()


def test_active_state_paths_cannot_escape_the_project_root(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    state = ActiveMapState(
        name="escape",
        bbox=BoundingBox(40, 14, 41, 15),
        osm_path="../../outside.osm",
        xodr_path="data/maps/escape.xodr",
        device_registry={},
    )

    with pytest.raises(RuntimeStateError, match="escapes the project root"):
        state.to_profile(paths)


def test_legacy_env_state_is_read_only_fallback(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    state = load_active_map_state(
        paths=paths,
        environ={
            "ACTIVE_MAP_NAME": "legacy",
            "MAP_SW_LAT": "40",
            "MAP_SW_LON": "14",
            "MAP_NE_LAT": "41",
            "MAP_NE_LON": "15",
            "MAP_DEVICE_REGISTRY": '{"D1": [40.5, 14.5]}',
        },
    )
    assert state.source == "legacy-env"
    assert state.device_registry == {"D1": (40.5, 14.5)}
    assert not paths.active_map_state.exists()
