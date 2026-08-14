"""CARLA Osm2Odr conversion kept behind a lazy external boundary."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from motion.domain.maps import KEPT_WAY_TYPES, MapProfile


class MapConversionError(RuntimeError):
    pass


class CarlaOsmToOpenDriveConverter:
    def convert(self, profile: MapProfile) -> Path:
        try:
            carla = importlib.import_module("carla")
        except ImportError as error:
            raise MapConversionError(
                "CARLA Python API is required for OSM-to-OpenDRIVE conversion."
            ) from error
        try:
            osm_data = profile.osm_path.read_text(encoding="utf-8")
        except OSError as error:
            raise MapConversionError(f"Cannot read OSM map: {profile.osm_path}") from error
        settings = carla.Osm2OdrSettings()
        settings.set_osm_way_types(list(KEPT_WAY_TYPES))
        settings.proj_string = profile.proj_string
        try:
            xodr_data = carla.Osm2Odr.convert(osm_data, settings)
        except RuntimeError as error:
            raise MapConversionError("CARLA failed to convert the OSM extract.") from error
        if not xodr_data or "<OpenDRIVE" not in xodr_data:
            raise MapConversionError("CARLA produced an empty or invalid OpenDRIVE document.")
        profile.xodr_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = profile.xodr_path.with_suffix(profile.xodr_path.suffix + ".tmp")
        temporary.write_text(xodr_data, encoding="utf-8")
        os.replace(temporary, profile.xodr_path)
        return profile.xodr_path
