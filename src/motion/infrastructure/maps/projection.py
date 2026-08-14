"""Build the WGS84-to-CARLA transform used by the generated OpenDRIVE map."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Protocol

from motion.domain.maps import KEPT_WAY_TYPES

WGS84_EPSG_CODE = "EPSG:4326"


class CoordinateTransformer(Protocol):
    def transform(self, x: float, y: float) -> tuple[float, float]: ...


@dataclass(frozen=True, slots=True)
class GeoTransform:
    map_projection_string: str
    min_easting: float
    min_northing: float

    def to_carla(self, latitude: float, longitude: float) -> tuple[float, float]:
        transformer = map_transformer(self.map_projection_string)
        easting, northing = transformer.transform(longitude, latitude)
        return easting - self.min_easting, -(northing - self.min_northing)

    def to_xy(self, latitude_deg: float, longitude_deg: float) -> tuple[float, float]:
        return self.to_carla(latitude_deg, longitude_deg)


@cache
def map_transformer(map_projection_string: str) -> CoordinateTransformer:
    try:
        from pyproj import CRS, Transformer
    except ImportError as error:  # pragma: no cover - installation error
        raise RuntimeError("The 'pyproj' package is required for geographic projection.") from error
    map_crs = CRS.from_proj4(map_projection_string)
    return Transformer.from_crs(WGS84_EPSG_CODE, map_crs, always_xy=True)


def _load_node_coordinates(root: ET.Element) -> dict[str, tuple[float, float]]:
    coordinates: dict[str, tuple[float, float]] = {}
    for node in root.findall("node"):
        node_id = node.get("id")
        latitude = node.get("lat")
        longitude = node.get("lon")
        if node_id is None or latitude is None or longitude is None:
            continue
        coordinates[node_id] = (float(latitude), float(longitude))
    return coordinates


def _road_node_ids(root: ET.Element, kept_way_types: set[str]) -> set[str]:
    node_ids: set[str] = set()
    for way in root.findall("way"):
        highway_type = next(
            (tag.get("v") for tag in way.findall("tag") if tag.get("k") == "highway"),
            None,
        )
        if highway_type in kept_way_types:
            node_ids.update(
                node_ref for node in way.findall("nd") if (node_ref := node.get("ref")) is not None
            )
    return node_ids


def build_geo_transform(
    osm_path: Path,
    map_projection_string: str,
    kept_way_types: set[str] | None = None,
    *,
    transformer: CoordinateTransformer | None = None,
) -> GeoTransform:
    root = ET.parse(osm_path).getroot()
    node_coordinates = _load_node_coordinates(root)
    selected_types = set(KEPT_WAY_TYPES) if kept_way_types is None else kept_way_types
    road_coordinates = [
        node_coordinates[node_id]
        for node_id in _road_node_ids(root, selected_types)
        if node_id in node_coordinates
    ]
    if not road_coordinates:
        raise ValueError(f"No road nodes matching {sorted(selected_types)} in {osm_path}.")
    coordinate_transformer = transformer or map_transformer(map_projection_string)
    projected = [
        coordinate_transformer.transform(longitude, latitude)
        for latitude, longitude in road_coordinates
    ]
    return GeoTransform(
        map_projection_string=map_projection_string,
        min_easting=min(easting for easting, _ in projected),
        min_northing=min(northing for _, northing in projected),
    )
