"""Composition helpers for HERE adapters; kept outside domain/application code."""

from __future__ import annotations

from motion.config.settings import AppSettings
from motion.domain.maps import MapProfile

from .archive import HereArchive, RecordingFetcher
from .client import HereEndpointFetcher, RequestsJsonTransport
from .parser import IncidentParser, TrafficParser
from .provider import HereTrafficProvider, PayloadFetcher


def build_here_provider(
    settings: AppSettings,
    profile: MapProfile,
    *,
    road_filter: str = "",
) -> HereTrafficProvider:
    transport = RequestsJsonTransport()
    bbox = profile.bbox.to_here_bbox()
    flow_fetcher: PayloadFetcher = HereEndpointFetcher(
        transport=transport,
        api_key=settings.here.api_key,
        bbox=bbox,
        url=settings.here.flow_url,
        timeout_seconds=settings.here.request_timeout_seconds,
        use_deep_coverage=True,
    )
    incident_fetcher: PayloadFetcher = HereEndpointFetcher(
        transport=transport,
        api_key=settings.here.api_key,
        bbox=bbox,
        url=settings.here.incidents_url,
        timeout_seconds=settings.here.request_timeout_seconds,
    )
    if settings.here.archive_mode == "record":
        archive = HereArchive.for_new_session(
            archive_root=settings.paths.here_archives,
            map_name=profile.name,
            bounding_box=bbox,
            road_filter=road_filter,
        )
        flow_fetcher = RecordingFetcher(flow_fetcher, archive, "flow")
        incident_fetcher = RecordingFetcher(incident_fetcher, archive, "incidents")
    fallback = (profile.geo_origin_lat, profile.geo_origin_lon)
    return HereTrafficProvider(
        flow_fetcher=flow_fetcher,
        incident_fetcher=incident_fetcher,
        traffic_parser=TrafficParser(fallback),
        incident_parser=IncidentParser(fallback),
    )
