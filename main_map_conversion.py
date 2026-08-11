import os
import carla

from map_profile import KEPT_WAY_TYPES, get_active_profile
from osm_downloader import download_osm_extract, print_manual_instructions


AUTO_DOWNLOAD = False

profile = get_active_profile()

if not os.path.exists(profile.osm_path):
    if AUTO_DOWNLOAD:
        download_osm_extract(profile.bbox, profile.osm_path)
    else:
        print_manual_instructions(profile.bbox, profile.osm_path)
        raise SystemExit(1)

with open(profile.osm_path, mode="r", encoding="utf-8") as osm_file:
    osm_data = osm_file.read()

settings = carla.Osm2OdrSettings()
settings.set_osm_way_types(KEPT_WAY_TYPES)
settings.proj_string = profile.proj_string
xodr_data = carla.Osm2Odr.convert(osm_data, settings)

os.makedirs(os.path.dirname(profile.xodr_path) or ".", exist_ok=True)

with open(profile.xodr_path, mode="w", encoding="utf-8") as xodr_file:
    xodr_file.write(xodr_data)

print(f"[main_map_conversion] Wrote {profile.xodr_path}")