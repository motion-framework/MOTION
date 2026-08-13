"""Filesystem implementation of the map-artifact processing port."""

from __future__ import annotations

from pathlib import Path

from traffic_mirror.domain.geography import BoundingBox
from traffic_mirror.ports.maps import (
    MapArtifactProcessingResult,
    MapRepairOutcome,
)

from .geometry import (
    patch_object_overflows,
    patch_zero_length_geometries,
    scan_degenerate_geometries,
    scan_object_overflows,
)
from .osm_inspection import inspect_osm


class LocalMapArtifactProcessor:
    """Apply the characterized local OSM/OpenDRIVE inspection pipeline."""

    def osm_covers(self, path: Path, bbox: BoundingBox) -> bool:
        if not path.is_file():
            return False
        try:
            bounds = inspect_osm(path).bounds
        except (OSError, ValueError):
            return False
        if bounds is None:
            return False
        return (
            bounds.min_lat <= bbox.south_west_lat
            and bounds.min_lon <= bbox.south_west_lon
            and bounds.max_lat >= bbox.north_east_lat
            and bounds.max_lon >= bbox.north_east_lon
        )

    def repair_and_validate(self, path: Path) -> MapArtifactProcessingResult:
        _, degenerate = scan_degenerate_geometries(path)
        zero_repair = patch_zero_length_geometries(path) if degenerate else None
        _, overflows = scan_object_overflows(path)
        overflow_repair = patch_object_overflows(path) if overflows else None
        _, remaining_degenerate = scan_degenerate_geometries(path)
        _, remaining_overflows = scan_object_overflows(path)
        return MapArtifactProcessingResult(
            zero_length_repair=MapRepairOutcome(
                patched_count=zero_repair.patched_count if zero_repair else 0,
                backup_path=zero_repair.backup_path if zero_repair else None,
            ),
            object_overflow_repair=MapRepairOutcome(
                patched_count=overflow_repair.patched_count if overflow_repair else 0,
                backup_path=overflow_repair.backup_path if overflow_repair else None,
            ),
            remaining_degenerate_geometries=len(remaining_degenerate),
            remaining_object_overflows=len(remaining_overflows),
        )
