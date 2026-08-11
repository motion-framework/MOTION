import os
import carla

from map_profile import get_active_profile
from traffic_mirror import CARLA_HOST, CARLA_PORT, geo_to_carla


MAX_ROAD_DISTANCE_METERS = 8.0
SHAPE_SAMPLES_PER_SEGMENT = 3
CONNECTION_TIMEOUT_SECONDS = 10.0


def _distance_to_nearest_road(carla_map: carla.Map, x: float, y: float) -> float:
    location = carla.Location(x=x, y=y, z=0.0)
    waypoint = carla_map.get_waypoint(location, project_to_road=True)
    if waypoint is None:
        return float("inf")
    road_location = waypoint.transform.location
    return ((x - road_location.x) ** 2 + (y - road_location.y) ** 2) ** 0.5


def _check_point(carla_map: carla.Map, label: str, latitude: float, longitude: float) -> bool:
    x, y = geo_to_carla(latitude, longitude)
    distance = _distance_to_nearest_road(carla_map, x, y)
    passed = distance <= MAX_ROAD_DISTANCE_METERS
    verdict = "OK  " if passed else "FAIL"
    print(f"  [{verdict}] {label:<28} geo=({latitude:.5f}, {longitude:.5f}) "
          f"-> carla=({x:.1f}, {y:.1f})  road distance={distance:.2f} m")
    return passed


def main() -> int:
    client = carla.Client(CARLA_HOST, CARLA_PORT)
    client.set_timeout(CONNECTION_TIMEOUT_SECONDS)
    carla_map = client.get_world().get_map()

    world = client.get_world()
    loaded_map_name = world.get_map().name
    if "opendrive" not in loaded_map_name.lower():
        raise SystemExit(
            f"CARLA has '{loaded_map_name}' loaded, not your provisioned map. "
            "This check would measure your coordinates against the wrong roads. "
            "Load your map first (run traffic_mirror.py or init_main_map.py), then run this check."
        )

    carla_map = world.get_map()

    profile = get_active_profile()
    print(f"\nAutomated calibration check for map '{profile.name}'")
    print(f"Threshold: markers must lie within {MAX_ROAD_DISTANCE_METERS} m of a road.\n")

    failures = 0

    print("Field devices:")
    from device_traffic_feed import DEVICE_REGISTRY
    for device_id, (latitude, longitude) in DEVICE_REGISTRY.items():
        if not _check_point(carla_map, device_id, latitude, longitude):
            failures += 1

    print("\nHERE segments (sampled shape points):")
    try:
        from here_traffic import HERE_API_KEY, TrafficFetcher, TrafficParser
        fetcher = TrafficFetcher(HERE_API_KEY, profile.bbox.to_here_bbox())
        parser = TrafficParser(fallback_coords=(profile.geo_origin_lat, profile.geo_origin_lon))
        segments = parser.parse(fetcher.fetch())
    except Exception as error:
        print(f"  Skipped ({error}).")
        segments = []

    road_filter = os.environ.get("MIRROR_ROAD_FILTER", "")
    if road_filter:
        segments = [s for s in segments if road_filter.lower() in s.description.lower()]

    bbox = profile.bbox
    for segment in segments:
        all_points = list(segment.shape_points) or [(segment.lat, segment.lon)]
        points = [
            (latitude, longitude) for latitude, longitude in all_points
            if bbox.south_west_lat <= latitude <= bbox.north_east_lat
            and bbox.south_west_lon <= longitude <= bbox.north_east_lon
        ]
        skipped_count = len(all_points) - len(points)
        if skipped_count:
            print(f"  [SKIP] {segment.description[:22]}: {skipped_count} shape "
                  f"point(s) outside the map bbox (road extends past the map edge).")
        if not points:
            continue

        step = max(1, (len(points) - 1) // max(1, SHAPE_SAMPLES_PER_SEGMENT - 1))
        for point_index in range(0, len(points), step):
            latitude, longitude = points[point_index]
            label = f"{segment.description[:22]} pt{point_index}"
            if not _check_point(carla_map, label, latitude, longitude):
                failures += 1

    print()
    if failures:
        print(f"RESULT: FAIL -- {failures} marker(s) off the road network.")
        print("Likely causes: proj_string/geo origin mismatch, ")
        print("wrong active map loaded in CARLA, ")
        print("or KEPT_WAY_TYPES drift between conversion and geo_transform. Run verify_map_calibration.py to inspect visually. ")
        return 1

    print("RESULT: PASS -- all markers lie on the road network. ")
    print("Note: this proves markers are ON roads, not on the CORRECT roads. ")
    print("For a newly provisioned map, run verify_map_calibration.py once. ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())