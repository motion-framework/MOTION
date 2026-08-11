import carla

from map_profile import get_active_profile
from traffic_mirror import CARLA_HOST, CARLA_PORT, geo_to_carla


MARKER_Z = 3.0
MARKER_LIFETIME = 180.0
CONNECTION_TIMEOUT_SECONDS = 10.0
MAX_SEGMENTS_TO_DISPLAY = 15
SEGMENT_DESCRIPTION_DISPLAY_WIDTH = 35


def verify_devices(debug: carla.DebugHelper) -> None:
    try:
        from device_traffic_feed import DEVICE_REGISTRY
    except Exception as error:
        print(f"\nSkipping device check ({error}).")
        return

    print(f"\nChecking {len(DEVICE_REGISTRY)} registered devices...")
    for device_id, (latitude, longitude) in DEVICE_REGISTRY.items():
        try:
            x, y = geo_to_carla(latitude, longitude)
            location = carla.Location(x=x, y=y, z=MARKER_Z)
            debug.draw_point(location, size=0.4, color=carla.Color(255, 0, 0), life_time=MARKER_LIFETIME)
            debug.draw_string(location, device_id, draw_shadow=False,
                               color=carla.Color(255, 255, 0), life_time=MARKER_LIFETIME)
            print(f"  {device_id}: geo=({latitude}, {longitude}) -> carla=({x:.2f}, {y:.2f})  [red marker]")
        except Exception as error:
            print(f"  {device_id}: could not place marker ({error}).")


def verify_here_segments(debug: carla.DebugHelper) -> None:
    try:
        from here_traffic import HERE_API_KEY, TrafficFetcher, TrafficParser

        profile = get_active_profile()
        fetcher = TrafficFetcher(HERE_API_KEY, profile.bbox.to_here_bbox())
        parser = TrafficParser(fallback_coords=(profile.geo_origin_lat, profile.geo_origin_lon))
        segments = parser.parse(fetcher.fetch())
    except Exception as error:
        print(f"\nSkipping HERE segment check ({error}). Confirm HERE_API_KEY is set in .env.")
        return

    print(f"\nChecking {len(segments)} HERE segments...")
    for segment in segments[:MAX_SEGMENTS_TO_DISPLAY]:
        description = segment.description[:SEGMENT_DESCRIPTION_DISPLAY_WIDTH]
        try:
            x, y = geo_to_carla(segment.lat, segment.lon)
            location = carla.Location(x=x, y=y, z=MARKER_Z + 1.0)
            debug.draw_point(location, size=0.3, color=carla.Color(0, 120, 255), life_time=MARKER_LIFETIME)
            print(f"  {description:<{SEGMENT_DESCRIPTION_DISPLAY_WIDTH}} -> carla=({x:.2f}, {y:.2f})  [blue marker]")
        except Exception as error:
            print(f"  {description}: could not place marker ({error}).")


def verify_bbox_corners(debug: carla.DebugHelper) -> None:
    profile = get_active_profile()
    bbox = profile.bbox
    corner_points = {
        "SW": (bbox.south_west_lat, bbox.south_west_lon),
        "NE": (bbox.north_east_lat, bbox.north_east_lon),
        "SE": (bbox.south_west_lat, bbox.north_east_lon),
        "NW": (bbox.north_east_lat, bbox.south_west_lon),
        "CENTER": (bbox.center_lat, bbox.center_lon),
    }

    print(f"\nChecking bbox corners for active map '{profile.name}'...")
    for label, (latitude, longitude) in corner_points.items():
        try:
            x, y = geo_to_carla(latitude, longitude)
            location = carla.Location(x=x, y=y, z=MARKER_Z + 2.0)
            debug.draw_point(location, size=0.5, color=carla.Color(0, 255, 0), life_time=MARKER_LIFETIME)
            debug.draw_string(location, label, draw_shadow=False, color=carla.Color(0, 255, 0), life_time=MARKER_LIFETIME)
            print(f"  {label:<7} -> carla=({x:.2f}, {y:.2f})  [green marker]")
        except Exception as error:
            print(f"  {label:<7}: could not place marker ({error}).")


def main() -> None:
    client = carla.Client(CARLA_HOST, CARLA_PORT)
    client.set_timeout(CONNECTION_TIMEOUT_SECONDS)
    world = client.get_world()
    debug = world.debug

    verify_bbox_corners(debug)
    verify_devices(debug)
    verify_here_segments(debug)

    print("\nDone. Look at the CARLA window from above.")
    print("Green  = bbox corners  -> should form a rectangle that roughly frames the visible roads.")
    print("Red    = field devices -> should sit near the streets named in device_traffic_feed.py comments.")
    print("Blue   = HERE segments -> should sit on real roads, not scattered off-map.")


if __name__ == "__main__":
    main()