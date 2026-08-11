import math
import os
import carla
import requests
import here_archive

from dataclasses import dataclass, replace
from dotenv import load_dotenv
from map_profile import MapProfile, get_active_profile


load_dotenv()


HERE_API_KEY: str = os.getenv("HERE_API_KEY", "")
HERE_FLOW_URL: str = "https://data.traffic.hereapi.com/v7/flow"
SPEED_LIMIT_KMH: float = 50.0
TRAFFIC_MANAGER_PORT: int = 8000
REQUEST_TIMEOUT_S: int = 10
USE_DEEP_COVERAGE: bool = True
JAM_THRESHOLD_FREE: float = 3.0
JAM_THRESHOLD_SLOW: float = 7.0
TRAVERSABILITY_CLOSED: str = "closed"
HERE_INCIDENTS_URL: str = "https://data.traffic.hereapi.com/v7/incidents"
INCIDENT_MATCH_RADIUS_M: float = 150.0
METRES_PER_DEGREE_LATITUDE: float = 111_320.0
HERE_ARCHIVE_MODE: str = os.getenv("HERE_ARCHIVE_MODE", "off").lower()
FLOW_ENDPOINT_NAME: str = "flow"
INCIDENTS_ENDPOINT_NAME: str = "incidents"


@dataclass(frozen=True)
class TrafficSegment:
    description: str
    length_m: float
    speed_kmh: float
    free_kmh: float
    jam_factor: float
    confidence: float
    incidents_nearby: int = 0
    road_closure: bool = False
    lat: float = 0.0
    lon: float = 0.0
    shape_points: tuple[tuple[float, float], ...] = ()
    functional_class: int = 0

    @property
    def congestion_level(self) -> str:
        if self.jam_factor < JAM_THRESHOLD_FREE:
            return "FREE"
        if self.jam_factor < JAM_THRESHOLD_SLOW:
            return "SLOW"
        return "JAM"


def _cumulative_distances_meters(points: list[tuple[float, float]]) -> list[float]:
    distances = [0.0]
    for previous_point, next_point in zip(points, points[1:]):
        distances.append(distances[-1] + _approx_distance_meters(previous_point, next_point))
    return distances


def _slice_polyline(
    points: list[tuple[float, float]],
    cumulative: list[float],
    start_m: float,
    end_m: float,
) -> tuple[tuple[float, float], ...]:
    inside = [point for point, travelled in zip(points, cumulative) if start_m <= travelled <= end_m]
    if len(inside) >= 2:
        return tuple(inside)
    middle_m = (start_m + end_m) / 2.0
    nearest = min(range(len(points)), key=lambda index: abs(cumulative[index] - middle_m))
    return tuple(points[max(0, nearest - 1):nearest + 2])


def _approx_distance_meters(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    first_lat, first_lon = first
    second_lat, second_lon = second

    mean_latitude_rad = math.radians((first_lat + second_lat) / 2.0)
    north_south_m = (second_lat - first_lat) * METRES_PER_DEGREE_LATITUDE
    east_west_m = (
        (second_lon - first_lon)
        * METRES_PER_DEGREE_LATITUDE
        * math.cos(mean_latitude_rad)
    )
    return math.hypot(east_west_m, north_south_m)


def _parse_shape(
    shape: dict, fallback_coords: tuple[float, float]
) -> tuple[float, float, tuple[tuple[float, float], ...], int]:
    links = shape.get("links", [])
    points = tuple(
        (point["lat"], point["lng"])
        for link in links
        for point in link.get("points", [])
    )

    functional_class = next(
        (int(link["functionalClass"]) for link in links if "functionalClass" in link),
        0,
    )

    if not points:
        return (*fallback_coords, (), functional_class)

    average_lat = sum(p[0] for p in points) / len(points)
    average_lon = sum(p[1] for p in points) / len(points)
    return average_lat, average_lon, points, functional_class


class TrafficFetcher:
    def __init__(
        self,
        api_key: str,
        bbox: str,
        url: str = HERE_FLOW_URL,
        use_deep_coverage: bool = False,
    ) -> None:
        if not api_key:
            raise ValueError("HERE_API_KEY is empty. Add HERE_API_KEY=your_key to the .env file and restart the script. ")
        self._api_key = api_key
        self._bbox = bbox
        self._url = url
        self._use_deep_coverage = use_deep_coverage

    def fetch(self) -> dict:
        params: dict = {
            "apiKey": self._api_key,
            "in": self._bbox,
            "locationReferencing": "shape",
        }
        if self._use_deep_coverage:
            params["advancedFeatures"] = "deepCoverage"

        response = requests.get(self._url, params=params, timeout=REQUEST_TIMEOUT_S)
        response.raise_for_status()
        return response.json()


class RecordingTrafficFetcher:
    def __init__(
        self,
        wrapped_fetcher: TrafficFetcher,
        archive: "here_archive.HereArchive",
        endpoint_name: str,
    ) -> None:
        self._wrapped_fetcher = wrapped_fetcher
        self._archive = archive
        self._endpoint_name = endpoint_name

    def fetch(self) -> dict:
        payload = self._wrapped_fetcher.fetch()
        self._archive.record(self._endpoint_name, payload)
        return payload


def build_traffic_fetchers(profile: MapProfile):
    bounding_box = profile.bbox.to_here_bbox()
    live_flow_fetcher = TrafficFetcher(HERE_API_KEY, bounding_box, use_deep_coverage=USE_DEEP_COVERAGE)
    live_incident_fetcher = TrafficFetcher(HERE_API_KEY, bounding_box, url=HERE_INCIDENTS_URL)

    if HERE_ARCHIVE_MODE != "record":
        return live_flow_fetcher, live_incident_fetcher

    archive = here_archive.HereArchive.for_new_session(
        map_name=profile.name,
        bounding_box=bounding_box,
        road_filter=os.getenv("MIRROR_ROAD_FILTER", ""),
    )

    return (
        RecordingTrafficFetcher(live_flow_fetcher, archive, FLOW_ENDPOINT_NAME),
        RecordingTrafficFetcher(live_incident_fetcher, archive, INCIDENTS_ENDPOINT_NAME),
    )


class TrafficParser:
    def __init__(self, fallback_coords: tuple[float, float]) -> None:
        self._fallback_coords = fallback_coords

    def _resolve_coords(self, shape: dict) -> tuple[float, float, tuple[tuple[float, float], ...], int]:
        lat, lon, points, functional_class = _parse_shape(shape, self._fallback_coords)
        if not points:
            print("[TrafficParser WARNING] Segment has no shape points. Using fallback coordinates. ")
        return lat, lon, points, functional_class

    def parse(self, raw: dict) -> list[TrafficSegment]:
        segments: list[TrafficSegment] = []

        for result in raw.get("results", []):
            flow_data: dict = result.get("currentFlow", {})
            location: dict = result.get("location", {})

            free_ms = flow_data.get("freeFlow")
            speed_ms = flow_data.get("speed")
            if speed_ms is None:
                speed_ms = free_ms
            if free_ms is None:
                free_ms = speed_ms
            if speed_ms is None:
                continue

            description: str = location.get("description", "unknown")
            lat, lon, shape_points, functional_class = self._resolve_coords(location.get("shape", {}))

            base_segment = TrafficSegment(
                description=description,
                length_m=location.get("length", 0.0),
                speed_kmh=round(speed_ms * 3.6, 1),
                free_kmh=round(free_ms * 3.6, 1),
                jam_factor=flow_data.get("jamFactor", 0.0),
                confidence=flow_data.get("confidence", 1.0),
                incidents_nearby=0,
                road_closure=(str(flow_data.get("traversability", "open")).lower() == TRAVERSABILITY_CLOSED),
                lat=lat,
                lon=lon,
                shape_points=shape_points,
                functional_class=functional_class,
            )

            segments.extend(self._expand_subsegments(base_segment, flow_data))

        return segments

    def _expand_subsegments(self, base: TrafficSegment, flow_data: dict) -> list[TrafficSegment]:
        raw_subsegments = flow_data.get("subSegments", [])
        points = list(base.shape_points)
        if not raw_subsegments or len(points) < 2:
            return [base]

        cumulative = _cumulative_distances_meters(points)
        pieces: list[TrafficSegment] = []
        start_m = 0.0
        for raw in raw_subsegments:
            piece_length_m = float(raw.get("length", 0.0))
            if piece_length_m <= 0.0:
                continue
            end_m = min(start_m + piece_length_m, cumulative[-1])
            piece_points = _slice_polyline(points, cumulative, start_m, end_m)
            piece_speed_ms = float(raw.get("speed", base.speed_kmh / 3.6))
            piece_free_ms = float(raw.get("freeFlow", base.free_kmh / 3.6))
            pieces.append(replace(
                base,
                length_m=end_m - start_m,
                speed_kmh=round(piece_speed_ms * 3.6, 1),
                free_kmh=round(piece_free_ms * 3.6, 1),
                jam_factor=float(raw.get("jamFactor", base.jam_factor)),
                confidence=float(raw.get("confidence", base.confidence)),
                lat=sum(point[0] for point in piece_points) / len(piece_points),
                lon=sum(point[1] for point in piece_points) / len(piece_points),
                shape_points=piece_points,
            ))
            start_m = end_m

        if not pieces:
            return [base]
        return pieces


@dataclass(frozen=True)
class TrafficIncident:
    description: str
    incident_type: str
    criticality: str
    road_closed: bool
    lat: float
    lon: float


class IncidentParser:
    def __init__(self, fallback_coords: tuple[float, float]) -> None:
        self._fallback_coords = fallback_coords

    def parse(self, raw: dict) -> list[TrafficIncident]:
        incidents: list[TrafficIncident] = []

        for result in raw.get("results", []):
            details: dict = result.get("incidentDetails", {})
            location: dict = result.get("location", {})

            lat, lon, _points, _functional_class = _parse_shape(location.get("shape", {}), self._fallback_coords)
            description = details.get("description", {}).get(
                "value", details.get("type", "unknown")
            )

            incidents.append(TrafficIncident(
                description=description,
                incident_type=details.get("type", "unknown"),
                criticality=details.get("criticality", "unknown"),
                road_closed=bool(details.get("roadClosed", False)),
                lat=lat,
                lon=lon,
            ))

        return incidents


def enrich_segments_with_incidents(
    segments: list[TrafficSegment],
    incidents: list[TrafficIncident],
) -> list[TrafficSegment]:
    if not incidents:
        return segments

    enriched_segments: list[TrafficSegment] = []

    for segment in segments:
        nearby_incidents = [
            incident for incident in incidents
            if _approx_distance_meters(
                (segment.lat, segment.lon), (incident.lat, incident.lon)
            ) <= INCIDENT_MATCH_RADIUS_M
        ]
        closed_by_incident = any(incident.road_closed for incident in nearby_incidents)

        enriched_segments.append(replace(
            segment,
            incidents_nearby=len(nearby_incidents),
            road_closure=segment.road_closure or closed_by_incident,
        ))

    return enriched_segments


class TrafficReporter:
    def __init__(self, profile: MapProfile) -> None:
        self._profile = profile

    def report(self, segments: list[TrafficSegment]) -> None:
        print(f"\n--- {self._profile.name.upper()} TRAFFIC REPORT ---")

        for index, segment in enumerate(segments, start=1):
            print(
                f"[{index:>2}] {segment.description:<35} "
                f"{segment.speed_kmh:>5.1f} km/h  "
                f"jam={segment.jam_factor:.1f}/10  "
                f"incidents={segment.incidents_nearby}  "
                f"closed={segment.road_closure}  "
                f"[{segment.congestion_level}]  "
                f"confidence={segment.confidence:.0%} "
                f"fc={segment.functional_class} "
            )

        if segments:
            average_speed_kmh = sum(segment.speed_kmh for segment in segments) / len(segments)
            print(f"\n  Average speed: {average_speed_kmh:.1f} km/h")

        print("--------------------------------------\n")


class TrafficApplicator:
    def __init__(
        self,
        client: carla.Client,
        world: carla.World,
        speed_limit_kmh: float = SPEED_LIMIT_KMH,
    ) -> None:
        self._world: carla.World = world
        self._speed_limit_kmh: float = speed_limit_kmh

        try:
            self._tm = client.get_trafficmanager(TRAFFIC_MANAGER_PORT)
        except Exception as error:
            raise RuntimeError(
                f"TrafficApplicator: cannot connect to TrafficManager on port {TRAFFIC_MANAGER_PORT}. "
                f"Make sure CARLA is running before calling this. "
                f"Original error: {error} "
            ) from error

    def apply(self, segments: list[TrafficSegment]) -> int:
        if not segments:
            print("[TrafficApplicator] No segments provided. Skipping.")
            return 0
        average_speed_kmh = sum(segment.speed_kmh for segment in segments) / len(segments)

        speed_percentage_difference = max(
            0.0,
            (self._speed_limit_kmh - average_speed_kmh) / self._speed_limit_kmh * 100.0,
        )

        updated_vehicle_count = 0
        for vehicle in self._world.get_actors().filter("vehicle.*"):
            if not vehicle.is_alive:
                continue
            try:
                self._tm.vehicle_percentage_speed_difference(vehicle, speed_percentage_difference)
                updated_vehicle_count += 1
            except Exception as error:

                print(f"[TrafficApplicator] Could not update vehicle {vehicle.id}: {error} ")

                continue

        print(
            f"[TrafficApplicator] Updated {updated_vehicle_count} vehicles to "
            f"avg {average_speed_kmh:.1f} km/h (pct_diff={speed_percentage_difference:+.1f}%). "
        )

        return updated_vehicle_count


class TrafficService:
    def __init__(self, client: carla.Client, world: carla.World, profile: MapProfile | None = None) -> None:
        self._profile = profile or get_active_profile()
        self._fetcher, self._incident_fetcher = build_traffic_fetchers(self._profile)
        self._parser = TrafficParser(fallback_coords=(self._profile.geo_origin_lat, self._profile.geo_origin_lon))
        self._incident_parser = IncidentParser(fallback_coords=(self._profile.geo_origin_lat, self._profile.geo_origin_lon))
        self._reporter = TrafficReporter(self._profile)
        self._applicator = TrafficApplicator(client, world, self._profile.speed_limit_kmh)

    def update(self, apply_speeds: bool = True) -> list[TrafficSegment]:
        print(f"[TrafficService] Fetching live {self._profile.name} traffic...")
        raw: dict = self._fetcher.fetch()
        segments: list[TrafficSegment] = self._parser.parse(raw)
        segments = enrich_segments_with_incidents(segments, self._fetch_incidents())
        self._reporter.report(segments)
        if apply_speeds:
            self._applicator.apply(segments)
        return segments

    def _fetch_incidents(self) -> list[TrafficIncident]:
        try:
            return self._incident_parser.parse(self._incident_fetcher.fetch())
        except Exception as error:
            print(
                f"[TrafficService] Incident fetch failed ({error}). "
                "Continuing with flow data only; incidents_nearby will be 0."
            )
            return []