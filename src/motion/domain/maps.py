"""Map profiles and map-build metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .geography import BoundingBox

KEPT_WAY_TYPES: tuple[str, ...] = (
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
)


@dataclass(frozen=True, slots=True)
class MapProfile:
    name: str
    bbox: BoundingBox
    osm_path: Path
    xodr_path: Path
    speed_limit_kmh: float = 50.0
    geo_origin_override: tuple[float, float] | None = None
    device_registry: dict[str, tuple[float, float]] = field(default_factory=dict)

    @property
    def geo_origin_lat(self) -> float:
        return self.geo_origin_override[0] if self.geo_origin_override else self.bbox.center_lat

    @property
    def geo_origin_lon(self) -> float:
        return self.geo_origin_override[1] if self.geo_origin_override else self.bbox.center_lon

    @property
    def proj_string(self) -> str:
        return (
            f"+proj=tmerc +lat_0={self.geo_origin_lat} "
            f"+lon_0={self.geo_origin_lon} "
            "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        )
