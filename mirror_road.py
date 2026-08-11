import math
import argparse
import json
import os
import subprocess
import sys

from collections import defaultdict
from dataclasses import replace
from dotenv import set_key
from here_traffic import HERE_API_KEY, TrafficFetcher, TrafficParser, TrafficSegment
from map_profile import BoundingBox, DEFAULT_CENTER_RADIUS_METERS


DEVICES_PER_ROAD = 4
PROVISION_SCRIPT = "provision_map.py"
GEO_FILTER_RADIUS_METERS = 500.0
MINIMUM_REALTIME_CONFIDENCE = 0.71
MOTORWAY_FUNCTIONAL_CLASS_CEILING = 2
UNKNOWN_FUNCTIONAL_CLASS = 0


def _fetch_segments(latitude: float, longitude: float, radius: float) -> list[TrafficSegment]:
    bbox = BoundingBox.from_center(latitude, longitude, radius)
    fetcher = TrafficFetcher(HERE_API_KEY, bbox.to_here_bbox())
    segments = TrafficParser(fallback_coords=(latitude, longitude)).parse(fetcher.fetch())
    if not segments:
        raise SystemExit(
            "HERE returned no traffic segments for this area. "
            "Try a larger --radius or coordinates in a denser road network."
        )
    return segments


def _group_by_road(segments: list[TrafficSegment]) -> list[tuple[str, list[TrafficSegment]]]:
    by_name: dict[str, list[TrafficSegment]] = defaultdict(list)
    for segment in segments:
        by_name[segment.description].append(segment)
    return sorted(by_name.items(), key=lambda item: len(item[1]), reverse=True)


def _representative(road_segments: list[TrafficSegment], center: tuple[float, float]) -> TrafficSegment:
    center_lat, center_lon = center
    return min(road_segments, key=lambda s: (s.lat - center_lat) ** 2 + (s.lon - center_lon) ** 2)


def _segments_near_center(
    segments: list[TrafficSegment],
    center: tuple[float, float],
    radius_meters: float,
) -> list[TrafficSegment]:
    center_lat, center_lon = center
    metres_per_degree_lat = 111_320.0
    metres_per_degree_lon = metres_per_degree_lat * math.cos(math.radians(center_lat))

    def nearest_shape_distance_meters(segment: TrafficSegment) -> float:
        polyline = list(segment.shape_points) or [(segment.lat, segment.lon)]
        best = float("inf")
        for point_lat, point_lon in polyline:
            north_south_m = (point_lat - center_lat) * metres_per_degree_lat
            east_west_m = (point_lon - center_lon) * metres_per_degree_lon
            best = min(best, math.hypot(north_south_m, east_west_m))
        return best

    return [
        segment for segment in segments
        if nearest_shape_distance_meters(segment) <= radius_meters
    ]


def _metres_between(
    point_a: tuple[float, float],
    point_b: tuple[float, float],
    reference_latitude: float,
) -> float:
    metres_per_degree_latitude = 111_320.0
    metres_per_degree_longitude = 111_320.0 * math.cos(math.radians(reference_latitude))
    delta_latitude_metres = (point_a[0] - point_b[0]) * metres_per_degree_latitude
    delta_longitude_metres = (point_a[1] - point_b[1]) * metres_per_degree_longitude
    return math.hypot(delta_latitude_metres, delta_longitude_metres)


def _polyline_length_m(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    reference_latitude = points[0][0]
    return sum(
        _metres_between(points[i], points[i + 1], reference_latitude)
        for i in range(len(points) - 1)
    )


def _cut_road_around_center(
    points: tuple[tuple[float, float], ...],
    half_length_metres: float,
) -> list[tuple[float, float]]:
    if len(points) < 2:
        return list(points)

    reference_latitude = points[0][0]
    cumulative = [0.0]

    for i in range(len(points) - 1):
        cumulative.append(cumulative[-1] + _metres_between(points[i], points[i + 1], reference_latitude))
    
    total_length = cumulative[-1]

    centre_distance = total_length / 2.0
    keep_start = max(0.0, centre_distance - half_length_metres)
    keep_end = min(total_length, centre_distance + half_length_metres)

    if keep_start <= 0.0 and keep_end >= total_length:
        return list(points)

    def point_at_distance(target_distance: float) -> tuple[float, float]:
        for i in range(len(points) - 1):
            if cumulative[i] <= target_distance <= cumulative[i + 1]:
                span = cumulative[i + 1] - cumulative[i]
                fraction = 0.0 if span == 0 else (target_distance - cumulative[i]) / span
                latitude = points[i][0] + (points[i + 1][0] - points[i][0]) * fraction
                longitude = points[i][1] + (points[i + 1][1] - points[i][1]) * fraction
                return (latitude, longitude)
        return points[-1]

    cut = [point_at_distance(keep_start)]
    for i, point in enumerate(points):
        if keep_start < cumulative[i] < keep_end:
            cut.append(point)
    cut.append(point_at_distance(keep_end))
    return cut


def _select_main_road_segment(near_segments: list[TrafficSegment], center: tuple[float, float], ) -> TrafficSegment:
    center_lat, center_lon = center

    def nearest_shape_distance(segment: TrafficSegment) -> float:
        polyline = list(segment.shape_points) or [(segment.lat, segment.lon)]
        return min(
            math.hypot(point_lat - center_lat, point_lon - center_lon)
            for point_lat, point_lon in polyline
        )

    def is_motorway(segment: TrafficSegment) -> bool:
        return 0 < segment.functional_class <= MOTORWAY_FUNCTIONAL_CLASS_CEILING

    def has_realtime_data(segment: TrafficSegment) -> bool:
        return segment.confidence >= MINIMUM_REALTIME_CONFIDENCE

    def has_real_name(segment: TrafficSegment) -> bool:
        name = segment.description.strip().lower()
        return name not in ("", "unknown")

    urban_segments = [s for s in near_segments if not is_motorway(s)]
    if not urban_segments:
        print(
            "[mirror_road] WARNING: every nearby segment is a motorway "
            f"(functional class <= {MOTORWAY_FUNCTIONAL_CLASS_CEILING}). "
            "Using them anyway; the mirror will run at capped urban speeds."
        )
        urban_segments = near_segments

    named_segments = [s for s in urban_segments if has_real_name(s)]

    if not named_segments:
        print(
            "[mirror_road] WARNING: no named, non-motorway road found near your point. "
            "HERE returned only 'unknown' stretches here. "
            "Falling back to the nearest unnamed segment. "
            "Consider moving your --lat/--lon to a point on a road that HERE labels by name. "
        )

        named_segments = urban_segments

    realtime_named = [s for s in named_segments if has_realtime_data(s)]

    if realtime_named:
        candidates = realtime_named
    else:
        print(
            f"[mirror_road] WARNING: no named segment has real-time data "
            f"(confidence >= {MINIMUM_REALTIME_CONFIDENCE:.0%}). "
            "Using the best available; mirrored speeds may be historical."
        )
        candidates = named_segments

    roads_by_name: dict[str, list[TrafficSegment]] = defaultdict(list)

    for segment in candidates:
        roads_by_name[segment.description].append(segment)

    def road_sort_key(road_item: tuple[str, list[TrafficSegment]]) -> tuple:
        _road_name, road_segments = road_item
        segment_count = len(road_segments)
        average_confidence = sum(s.confidence for s in road_segments) / segment_count
        nearest_distance = min(nearest_shape_distance(s) for s in road_segments)
        return (segment_count, average_confidence, -nearest_distance)

    best_road_name, best_road_segments = max(roads_by_name.items(), key=road_sort_key)
    chosen = min(best_road_segments, key=nearest_shape_distance)

    print(
        f"[mirror_road] Main road chosen: '{chosen.description}' "
        f"({len(best_road_segments)} segment(s) near center, "
        f"confidence {chosen.confidence:.0%}, "
        f"functional class {chosen.functional_class}, "
        f"best of {len(roads_by_name)} candidate road(s))."
    )
    return chosen


def _choose_road(
    roads: list[tuple[str, list[TrafficSegment]]],
) -> tuple[str, list[TrafficSegment]]:
    print("\n  Roads HERE covers in this area:\n")
    print(f"  {'#':>3}  {'road':<38} {'segment':>4}  {'avg speed':>9}  {'jam':>4}")
    print("  " + "-" * 62)
    for index, (name, road_segments) in enumerate(roads, start=1):
        avg_speed = sum(s.speed_kmh for s in road_segments) / len(road_segments)
        avg_jam = sum(s.jam_factor for s in road_segments) / len(road_segments)
        display = name if len(name) <= 38 else name[:35] + "..."
        print(f"  {index:>3}  {display:<38} {len(road_segments):>4}  "
              f"{avg_speed:>7.1f} km/h  {avg_jam:>4.1f}")
    print()

    raw = input(f"Road number to mirror (1..{len(roads)}, or 'q' to quit): ").strip()
    if raw.lower() == "q":
        raise SystemExit(0)
    try:
        chosen_name, chosen_segments = roads[int(raw) - 1]
    except (ValueError, IndexError):
        raise SystemExit(f"'{raw}' is not one of 1..{len(roads)}.")

    if all(0 < s.functional_class <= MOTORWAY_FUNCTIONAL_CLASS_CEILING for s in chosen_segments):
        print(
            f"[mirror_road] NOTE: '{chosen_name}' is a motorway (functional class {chosen_segments[0].functional_class}). "
            "The functional class filter will exclude most local roads from the simulation. "
            "Consider a lower class road for urban traffic mirroring. "
        )

    return chosen_name, chosen_segments


def _device_positions(
    segment: TrafficSegment,
    device_count: int,
    map_bbox: BoundingBox,
) -> list[tuple[float, float]]:
    all_points = list(segment.shape_points) or [(segment.lat, segment.lon)]

    inside_points = [
        (latitude, longitude) for latitude, longitude in all_points
        if map_bbox.south_west_lat <= latitude <= map_bbox.north_east_lat
        and map_bbox.south_west_lon <= longitude <= map_bbox.north_east_lon
    ]
    if not inside_points:
        print(
            "[mirror_road] WARNING: no shape point of this road lies inside the map bbox. "
            "Using the full polyline; calibration will likely FAIL. "
            "Increase --radius, or pick a road closer to your chosen centre. "
        )
        inside_points = all_points

    points = sorted(inside_points)

    if len(points) == 1 or device_count == 1:
        return [points[0]] * device_count

    step = (len(points) - 1) / (device_count - 1)
    return [points[round(index * step)] for index in range(device_count)]


def _provision_geo_mirror(anchor_segment: TrafficSegment, args: argparse.Namespace) -> None:
    anchor_segment = replace(
        anchor_segment,
        shape_points=tuple(_cut_road_around_center(anchor_segment.shape_points, args.radius)),
    )
    kept_length_m = _polyline_length_m(list(anchor_segment.shape_points))
    print(
        f"[mirror_road] Road cut: keeping {kept_length_m:.0f} m of '{anchor_segment.description}', "
        f" centred on its midpoint (radius {args.radius:.0f} m each way from centre)."
    )

    anchor_lat, anchor_lon = anchor_segment.shape_points[len(anchor_segment.shape_points) // 2]
    print(f"[mirror_road] Map anchored at ({anchor_lat:.6f}, {anchor_lon:.6f}). ")

    map_bbox = BoundingBox.from_center(anchor_lat, anchor_lon, args.radius)

    registry = {
        f"{args.name.upper()}_{index + 1:03d}": position
        for index, position in enumerate(
            _device_positions(anchor_segment, DEVICES_PER_ROAD, map_bbox)
        )
    }

    for device_id, (device_lat, device_lon) in registry.items():
        print(f"[mirror_road]   {device_id}: ({device_lat:.6f}, {device_lon:.6f})")

    registry_json = json.dumps(registry)
    os.environ["MAP_DEVICE_REGISTRY"] = registry_json
    os.environ.pop("MIRROR_ROAD_FILTER", None)
    os.environ["MIRROR_GEO_FILTER"] = "1"
    set_key(".env", "MAP_DEVICE_REGISTRY", registry_json)
    set_key(".env", "MIRROR_ROAD_FILTER", "")
    set_key(".env", "MIRROR_GEO_FILTER", "1")

    os.environ["MIRROR_ANCHOR_FC"] = str(anchor_segment.functional_class)
    set_key(".env", "MIRROR_ANCHOR_FC", str(anchor_segment.functional_class))

    print(f"[mirror_road] Provisioning map '{args.name}' around the chosen road...")

    result = subprocess.run(
        [sys.executable, PROVISION_SCRIPT,
         "--lat", f"{anchor_lat:.6f}", "--lon", f"{anchor_lon:.6f}",
         "--radius", str(args.radius), "--name", args.name],
    )

    if result.returncode != 0:
        raise SystemExit(f"{PROVISION_SCRIPT} failed. See its output above.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pick and mirror a HERE covered road in a chosen area.")
    parser.add_argument("--lat", type=float, required=True, help="Area center latitude")
    parser.add_argument("--lon", type=float, required=True, help="Area center longitude")
    parser.add_argument("--radius", type=float, default=DEFAULT_CENTER_RADIUS_METERS,
                        help=f"Area + map half-width in metres (default {DEFAULT_CENTER_RADIUS_METERS:g})")
    parser.add_argument("--name", default="here_road", help="Identifier used for map files")
    parser.add_argument("--geo", action="store_true",
                        help="How far (metres) from --lat/--lon to search for a road to anchor on, in --geo mode. "
                             "Separate from --radius, which sets how much of the road is mirrored.")
    args = parser.parse_args()

    center = (args.lat, args.lon)

    segments = _fetch_segments(args.lat, args.lon, args.radius)
    print(f"[mirror_road] HERE coverage: {len(segments)} segments in this area.")
    roads = _group_by_road(segments)
    if args.geo:
        near_segments = _segments_near_center(segments, center, GEO_FILTER_RADIUS_METERS)
        if not near_segments:
            raise SystemExit(
                f"No HERE segment passes within {GEO_FILTER_RADIUS_METERS:.0f} m of "
                f"({args.lat:.5f}, {args.lon:.5f}). Increase --radius or the geo radius, "
                "or point at a road HERE actually covers."
            )
        print(f"[mirror_road] Geographic mode: {len(near_segments)} segment(s) within "
              f"{GEO_FILTER_RADIUS_METERS:.0f} m of your point (out of {len(segments)} in the area).")
        anchor_segment = _select_main_road_segment(near_segments, center)
    else:
        road_name, road_segments = _choose_road(roads)
        anchor_segment = _representative(road_segments, center)
        print(f"[mirror_road] Selected from menu: '{road_name}' "
              f"({len(anchor_segment.shape_points)} shape points).")

    _provision_geo_mirror(anchor_segment, args)

    print("\n[mirror_road] Done. Geo-filtered mirror ready.")
    print("[mirror_road] Next: start CARLA, then run: python traffic_mirror.py")
    print("[mirror_road] Recommended once per new map: python check_map_calibration.py")


if __name__ == "__main__":
    main()