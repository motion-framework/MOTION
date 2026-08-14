"""Automated and visual calibration against a loaded CARLA world."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from motion.config.runtime_state import ActiveMapState
from motion.config.settings import AppSettings
from motion.domain.maps import MapProfile
from motion.domain.traffic import TrafficSegment
from motion.ports.simulator import CoordinateProjector

from .lifecycle import CarlaLifecycle

MAX_ROAD_DISTANCE_METERS = 8.0
MARKER_Z_METERS = 3.0
MARKER_LIFETIME_SECONDS = 180.0
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    checked_points: int
    failed_points: int

    @property
    def passed(self) -> bool:
        return self.failed_points == 0


def check_loaded_world(
    *,
    world: Any,
    carla_module: Any,
    profile: MapProfile,
    projector: CoordinateProjector,
    segments: Sequence[TrafficSegment] = (),
    visual: bool = False,
) -> CalibrationResult:
    carla_map = world.get_map()
    debug = getattr(world, "debug", None)
    checked = 0
    failed = 0

    points: list[tuple[str, float, float, tuple[int, int, int]]] = [
        (device_id, latitude, longitude, (255, 0, 0))
        for device_id, (latitude, longitude) in profile.device_registry.items()
    ]
    for index, segment in enumerate(segments):
        shape = segment.shape_points or ((segment.lat, segment.lon),)
        step = max(1, (len(shape) - 1) // 2)
        for point_index in range(0, len(shape), step):
            latitude, longitude = shape[point_index]
            if profile.bbox.contains(latitude, longitude):
                points.append(
                    (
                        f"segment-{index}-point-{point_index}",
                        latitude,
                        longitude,
                        (0, 120, 255),
                    )
                )

    for label, latitude, longitude, color_rgb in points:
        x, y = projector.to_xy(latitude, longitude)
        location = carla_module.Location(x=x, y=y, z=0.0)
        waypoint = carla_map.get_waypoint(location, project_to_road=True)
        distance = float("inf")
        if waypoint is not None:
            road = waypoint.transform.location
            distance = ((x - road.x) ** 2 + (y - road.y) ** 2) ** 0.5
        checked += 1
        failed += int(distance > MAX_ROAD_DISTANCE_METERS)
        if visual and debug is not None:
            marker = carla_module.Location(x=x, y=y, z=MARKER_Z_METERS)
            debug.draw_point(
                marker,
                size=0.4,
                color=carla_module.Color(*color_rgb),
                life_time=MARKER_LIFETIME_SECONDS,
            )
            debug.draw_string(
                marker,
                label,
                draw_shadow=False,
                color=carla_module.Color(255, 255, 0),
                life_time=MARKER_LIFETIME_SECONDS,
            )
    return CalibrationResult(checked, failed)


def run_calibration(*, settings: AppSettings, state: ActiveMapState, visual: bool = False) -> int:
    """Standalone CLI diagnostic; it owns and cleans up its CARLA lifecycle."""

    from motion.infrastructure.here.factory import build_here_provider
    from motion.infrastructure.maps.projection import build_geo_transform

    profile = state.to_profile(settings.paths)
    projector = build_geo_transform(profile.osm_path, profile.proj_string)
    lifecycle = CarlaLifecycle(settings.carla)
    try:
        lifecycle.start_server_if_configured()
        lifecycle.wait_until_ready()
        world = lifecycle.load_open_drive_world(profile.xodr_path)
        provider_name = "HERE"
        try:
            provider = build_here_provider(settings, profile, road_filter=state.road_filter)
            provider_name = type(provider).__name__
            segments = provider.fetch_segments()
        except Exception as error:
            logger.warning(
                "HERE calibration acquisition failed; continuing with device "
                "anchors only (provider=%s, cause=%s)",
                provider_name,
                _exception_type_chain(error),
            )
            segments = []
        result = check_loaded_world(
            world=world,
            carla_module=lifecycle.carla,
            profile=profile,
            projector=projector,
            segments=segments,
            visual=visual,
        )
        return int(not result.passed)
    finally:
        lifecycle.close()


def _exception_type_chain(error: BaseException) -> str:
    """Return root-cause type names without exposing provider request data."""

    names: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.append(type(current).__name__)
        current = current.__cause__ or current.__context__
    return " <- ".join(names)
