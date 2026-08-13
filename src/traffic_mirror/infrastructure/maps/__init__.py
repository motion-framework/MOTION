"""OSM/OpenDRIVE inspection, conversion and projection adapters."""

from .geometry import (
    scan_degenerate_geometries,
    scan_object_overflows,
)
from .projection import GeoTransform, build_geo_transform

__all__ = [
    "GeoTransform",
    "build_geo_transform",
    "scan_degenerate_geometries",
    "scan_object_overflows",
]
