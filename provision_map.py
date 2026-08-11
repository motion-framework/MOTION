import argparse
import os
import subprocess
import sys

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from map_profile import MapProfile

MAP_CONVERSION_SCRIPT = "main_map_conversion.py"


def _set_bbox_env(args: argparse.Namespace) -> None:
    from dotenv import set_key
    from map_profile import BoundingBox, map_file_path

    if args.lat is not None and args.lon is not None:
        bbox = BoundingBox.from_center(args.lat, args.lon, args.radius)
    else:
        bbox = BoundingBox(
            south_west_lat=args.sw_lat, south_west_lon=args.sw_lon,
            north_east_lat=args.ne_lat, north_east_lon=args.ne_lon,
        )

    environment_values = {
        "MAP_SW_LAT": str(bbox.south_west_lat),
        "MAP_SW_LON": str(bbox.south_west_lon),
        "MAP_NE_LAT": str(bbox.north_east_lat),
        "MAP_NE_LON": str(bbox.north_east_lon),
        "ACTIVE_MAP_NAME": args.name,
        "MAP_OSM_PATH": map_file_path(args.name, f"{args.name}.osm"),
        "MAP_XODR_PATH": map_file_path(args.name, f"{args.name}_map.xodr"),
    }

    for key, value in environment_values.items():
        os.environ[key] = value
        set_key(".env", key, value)

    print(f"[provision_map] Saved '{args.name}' as the active map in .env")


def _download_osm(profile: "MapProfile") -> None:
    from osm_downloader import download_osm_extract

    print(f"[provision_map] Fetching OSM extract for '{profile.name}'...")
    download_osm_extract(profile.bbox, profile.osm_path)


def _download_osm_overwrite(profile: "MapProfile") -> None:
    from osm_downloader import download_osm_extract
    print(f"[provision_map] Re-fetching OSM extract for '{profile.name}'...")
    download_osm_extract(profile.bbox, profile.osm_path, overwrite=True)


def _convert_to_xodr() -> None:
    print("[provision_map] Converting OSM -> OpenDRIVE (subprocess)...")
    result = subprocess.run(
        [sys.executable, MAP_CONVERSION_SCRIPT],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"{MAP_CONVERSION_SCRIPT} failed. See output above.")


def _repair_geometry(xodr_path: str) -> None:
    from find_crosswalk_overflow import scan as scan_crosswalk_overflow
    from find_degenerate_geometry import scan as scan_degenerate_geometry
    from patch_crosswalk_overflow import patch as patch_crosswalk_overflow
    from patch_zero_length_geometry import patch as patch_zero_length_geometry

    print("[provision_map] Checking for degenerate geometry... ")
    degenerate_geometry_count = scan_degenerate_geometry(xodr_path)
    if degenerate_geometry_count:
        print(f"[provision_map] Found {degenerate_geometry_count} issue(s). Patching... ")
        patch_zero_length_geometry(xodr_path)
        remaining_count = scan_degenerate_geometry(xodr_path)
        if remaining_count:
            print(
                f"[provision_map] WARNING: {remaining_count} degenerate geometry issue(s) remain after patching. "
                "patch_zero_length_geometry.py only corrects exactly-zero lengths, not negative or non-numeric ones, "
                "inspect the .xodr file directly for the remainder. "
            )

    print("[provision_map] Checking for crosswalk overflow... ")
    crosswalk_overflow_count = scan_crosswalk_overflow(xodr_path)
    if crosswalk_overflow_count:
        print(f"[provision_map] Found {crosswalk_overflow_count} issue(s). Patching...")
        patch_crosswalk_overflow(xodr_path)
        remaining_count = scan_crosswalk_overflow(xodr_path)
        if remaining_count:
            print(f"[provision_map] WARNING: {remaining_count} crosswalk overflow issue(s) remain after patching. ")

    if not degenerate_geometry_count and not crosswalk_overflow_count:
        print("[provision_map] No known geometry defects found.")


def _parse_arguments() -> argparse.Namespace:
    from map_profile import DEFAULT_CENTER_RADIUS_METERS

    parser = argparse.ArgumentParser(description="Provision a new CARLA map from a lat/long.")
    parser.add_argument("--lat", type=float, help="Center latitude")
    parser.add_argument("--lon", type=float, help="Center longitude")
    parser.add_argument(
        "--radius", type=float, default=DEFAULT_CENTER_RADIUS_METERS,
        help=f"Half-width in metres (default {DEFAULT_CENTER_RADIUS_METERS:g})",
    )
    parser.add_argument("--sw-lat", type=float)
    parser.add_argument("--sw-lon", type=float)
    parser.add_argument("--ne-lat", type=float)
    parser.add_argument("--ne-lon", type=float)
    parser.add_argument("--name", required=True, help="Short identifier, used for file names")
    args = parser.parse_args()

    has_center_coordinates = args.lat is not None and args.lon is not None
    has_full_bounding_box = None not in (args.sw_lat, args.sw_lon, args.ne_lat, args.ne_lon)

    if has_center_coordinates and has_full_bounding_box:
        parser.error("Provide either --lat/--lon or --sw-*/--ne-* values, not both.")
    if not has_center_coordinates and not has_full_bounding_box:
        parser.error("Provide --lat/--lon (with optional --radius), or all four --sw-*/--ne-* values.")

    return args


def main() -> None:
    args = _parse_arguments()
    _set_bbox_env(args)

    from map_profile import get_active_profile
    profile = get_active_profile()
    print(f"[provision_map] Profile: {profile.name}")
    print(
        f"[provision_map]   bbox SW=({profile.bbox.south_west_lat}, {profile.bbox.south_west_lon}) "
        f"NE=({profile.bbox.north_east_lat}, {profile.bbox.north_east_lon})"
    )
    print(f"[provision_map]   osm_path={profile.osm_path}  xodr_path={profile.xodr_path}")

    if not os.path.exists(profile.osm_path):
        _download_osm(profile)
    else:
        from inspect_osm_bounds import _bounds_from_tag, _bounds_from_node_extent
        with open(profile.osm_path, "r", encoding="utf-8", errors="replace") as osm_file:
            content = osm_file.read()

        bounds = _bounds_from_tag(content) or _bounds_from_node_extent(content)
        center_lat, center_lon = profile.bbox.center_lat, profile.bbox.center_lon
        bbox = profile.bbox

        inside = bounds is not None and (
            bounds.min_lat <= bbox.south_west_lat
            and bounds.min_lon <= bbox.south_west_lon
            and bounds.max_lat >= bbox.north_east_lat
            and bounds.max_lon >= bbox.north_east_lon
        )
        if inside:
            print(f"[provision_map] Reusing existing OSM file: {profile.osm_path}")
        else:
            print(f"[provision_map] Existing {profile.osm_path} does not cover this area "
                  f"(center {center_lat:.4f},{center_lon:.4f}). Re-downloading. ")
            _download_osm_overwrite(profile)

    _convert_to_xodr()
    _repair_geometry(profile.xodr_path)

    print("\n[provision_map] Done.")
    print(
        f"[provision_map] To use this map elsewhere, set ACTIVE_MAP_NAME={args.name} "
        "or export the same MAP_SW_*/MAP_NE_* variables before running traffic_mirror or init_main_map.py."
    )
    print(
        "[provision_map] If running standalone: start CARLA, load this map, "
        "then run verify_map_calibration.py to visually confirm devices and roads line up. "
        "If launched from run_traffic_mirror.py, CARLA starts automatically. "
    )


if __name__ == "__main__":
    main()