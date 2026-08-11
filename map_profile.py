import math
import os
import json

from dataclasses import dataclass, field
from dotenv import load_dotenv


MAPS_ROOT = "maps"
METRES_PER_DEGREE_LATITUDE = 111_320.0
DEFAULT_CENTER_RADIUS_METERS = 1500.0


def map_file_path(map_name: str, filename: str) -> str:
    return os.path.join(MAPS_ROOT, map_name, filename)


@dataclass(frozen=True)
class BoundingBox:
    south_west_lat: float
    south_west_lon: float
    north_east_lat: float
    north_east_lon: float

    @property
    def center_lat(self) -> float:
        return (self.south_west_lat + self.north_east_lat) / 2

    @property
    def center_lon(self) -> float:
        return (self.south_west_lon + self.north_east_lon) / 2

    def to_overpass_bbox(self) -> str:
        return (
            f"{self.south_west_lat},"
            f"{self.south_west_lon},"
            f"{self.north_east_lat},"
            f"{self.north_east_lon}"
        )

    def to_here_bbox(self) -> str:
        return f"bbox:{self.south_west_lon},{self.south_west_lat},{self.north_east_lon},{self.north_east_lat}"

    @classmethod
    def from_center(
        cls,
        latitude: float,
        longitude: float,
        radius_meters: float = DEFAULT_CENTER_RADIUS_METERS,
    ) -> "BoundingBox":
        metres_per_degree_longitude = METRES_PER_DEGREE_LATITUDE * math.cos(math.radians(latitude))
        degrees_of_latitude = radius_meters / METRES_PER_DEGREE_LATITUDE
        degrees_of_longitude = radius_meters / metres_per_degree_longitude

        return cls(
            south_west_lat=latitude - degrees_of_latitude,
            south_west_lon=longitude - degrees_of_longitude,
            north_east_lat=latitude + degrees_of_latitude,
            north_east_lon=longitude + degrees_of_longitude,
        )


@dataclass(frozen=True)
class MapProfile:
    name: str
    bbox: BoundingBox
    osm_path: str
    xodr_path: str
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
            f"+proj=tmerc +lat_0={self.geo_origin_lat} +lon_0={self.geo_origin_lon} "
            "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        )

KEPT_WAY_TYPES: list[str] = [
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential",
]

MAP_PROFILES: dict[str, MapProfile] = {}

ACTIVE_MAP: str = ""


def _adhoc_profile_from_environment() -> MapProfile | None:
    required_bbox_variables = ("MAP_SW_LAT", "MAP_SW_LON", "MAP_NE_LAT", "MAP_NE_LON")
    if not all(os.environ.get(variable) for variable in required_bbox_variables):
        return None

    name = os.environ.get("ACTIVE_MAP_NAME", "adhoc_map")
    bbox = BoundingBox(
        south_west_lat=float(os.environ["MAP_SW_LAT"]),
        south_west_lon=float(os.environ["MAP_SW_LON"]),
        north_east_lat=float(os.environ["MAP_NE_LAT"]),
        north_east_lon=float(os.environ["MAP_NE_LON"]),
    )

    device_registry: dict[str, tuple[float, float]] = {}
    device_registry_json = os.environ.get("MAP_DEVICE_REGISTRY", "")
    
    if device_registry_json:
        try:
            device_registry = {
                device_id: (float(coords[0]), float(coords[1]))
                for device_id, coords in json.loads(device_registry_json).items()
            }
        except (ValueError, TypeError, KeyError, IndexError) as error:
            print(
                f"[map_profile] Ignoring invalid MAP_DEVICE_REGISTRY ({error}). "
                "Falling back to synthesized devices. "
            )

    return MapProfile(
        name=name,
        bbox=bbox,
        osm_path=os.environ.get("MAP_OSM_PATH", map_file_path(name, f"{name}.osm")),
        xodr_path=os.environ.get("MAP_XODR_PATH", map_file_path(name, f"{name}_map.xodr")),
        device_registry=device_registry,
    )


def get_active_profile() -> MapProfile:
    load_dotenv()

    adhoc_profile = _adhoc_profile_from_environment()
    if adhoc_profile is not None:
        return adhoc_profile

    profile_name = os.environ.get("ACTIVE_MAP_NAME", ACTIVE_MAP)
    try:
        return MAP_PROFILES[profile_name]
    except KeyError:
        raise SystemExit(
            f"No active map: ACTIVE_MAP_NAME={profile_name!r} is not in MAP_PROFILES, "
            "and no ad-hoc bounding box is set in the environment. "
            "Provision a map first (python provision_map.py ... or python mirror_road.py ...), " 
            "which writes it into .env, or add a named entry to MAP_PROFILES. "
        )