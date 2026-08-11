import xml.etree.ElementTree as ET

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
from pyproj import CRS, Transformer
from map_profile import KEPT_WAY_TYPES


WGS84_EPSG_CODE = "EPSG:4326"


@dataclass(frozen=True)
class GeoTransform:
    map_projection_string: str
    min_easting: float
    min_northing: float

    def to_carla(self, latitude: float, longitude: float) -> tuple[float, float]:
        transformer = _map_transformer(self.map_projection_string)
        easting, northing = transformer.transform(longitude, latitude)
        local_easting = easting - self.min_easting
        local_northing_flipped = -(northing - self.min_northing)
        return local_easting, local_northing_flipped


@lru_cache(maxsize=None)
def _map_transformer(map_projection_string: str) -> Transformer:
    map_crs = CRS.from_proj4(map_projection_string)
    return Transformer.from_crs(WGS84_EPSG_CODE, map_crs, always_xy=True)


def _load_node_coordinates(osm_root: ET.Element) -> dict[str, tuple[float, float]]:
    return {
        node.get("id"): (float(node.get("lat")), float(node.get("lon")))
        for node in osm_root.findall("node")
    }


def _find_road_node_ids(osm_root: ET.Element, kept_way_types: set[str]) -> set[str]:
    road_node_ids: set[str] = set()

    for way in osm_root.findall("way"):
        highway_type = next(
            (tag.get("v") for tag in way.findall("tag") if tag.get("k") == "highway"),
            None,
        )
        if highway_type in kept_way_types:
            road_node_ids.update(node_ref.get("ref") for node_ref in way.findall("nd"))

    return road_node_ids


def build_geo_transform(
    osm_path: str,
    map_projection_string: str,
    kept_way_types: Optional[set[str]] = None,
) -> GeoTransform:
    kept_way_types = kept_way_types or set(KEPT_WAY_TYPES)

    osm_root = ET.parse(osm_path).getroot()
    node_coordinates = _load_node_coordinates(osm_root)
    road_node_ids = _find_road_node_ids(osm_root, kept_way_types)

    road_coordinates = [
        node_coordinates[node_id]
        for node_id in road_node_ids
        if node_id in node_coordinates
    ]
    if not road_coordinates:
        raise ValueError(
            f"No nodes found belonging to {kept_way_types} in {osm_path}. "
            "Check that KEPT_WAY_TYPES matches what main_map_conversion.py actually used."
        )

    transformer = _map_transformer(map_projection_string)
    projected_points = [
        transformer.transform(longitude, latitude)
        for latitude, longitude in road_coordinates
    ]
    eastings = [easting for easting, _ in projected_points]
    northings = [northing for _, northing in projected_points]

    return GeoTransform(
        map_projection_string=map_projection_string,
        min_easting=min(eastings),
        min_northing=min(northings),
    )