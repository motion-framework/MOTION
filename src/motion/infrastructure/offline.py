"""HERE-compatible synthetic payloads for network-free UC-01 checks."""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from motion.domain.maps import MapProfile
from motion.infrastructure.here.parser import IncidentParser, TrafficParser
from motion.infrastructure.here.provider import HereTrafficProvider

DEFAULT_FREE_FLOW_KMH = 50.0
MINIMUM_SPEED_KMH = 10.0
SPEED_NOISE_RANGE_KMH = 8.0
SYNTHETIC_CONFIDENCE = 0.9
SYNTHETIC_FUNCTIONAL_CLASS = 3


class SyntheticPayloadFetcher:
    """Expose an in-memory payload through the same port as a HERE fetcher."""

    def __init__(self, payload_factory: Callable[[], dict[str, Any]]) -> None:
        self._payload_factory = payload_factory

    def fetch(self) -> dict[str, Any]:
        return self._payload_factory()


class HereCompatiblePayloadFactory:
    """Generate the HERE Traffic API v7 subset consumed by this repository."""

    def __init__(
        self,
        profile: MapProfile,
        registry: Mapping[str, tuple[float, float]],
        *,
        random_source: random.Random | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._profile = profile
        self._registry = dict(registry)
        self._random = random_source or random.Random()
        self._clock = clock or (lambda: datetime.now(UTC))

    def flow_payload(self) -> dict[str, Any]:
        points = self._ordered_points()
        free_flow_kmh = max(self._profile.speed_limit_kmh, DEFAULT_FREE_FLOW_KMH)
        free_flow_ms = free_flow_kmh / 3.6
        results: list[dict[str, Any]] = []
        for index, (start, end) in enumerate(pairwise(points), start=1):
            speed_kmh = max(
                MINIMUM_SPEED_KMH,
                free_flow_kmh - self._random.uniform(0.0, SPEED_NOISE_RANGE_KMH),
            )
            jam_factor = min(10.0, max(0.0, (1.0 - speed_kmh / free_flow_kmh) * 10.0))
            results.append(
                {
                    "location": {
                        "description": f"Synthetic {self._profile.name} segment {index}",
                        "length": self._distance_meters(start, end),
                        "shape": {
                            "links": [
                                {
                                    "functionalClass": SYNTHETIC_FUNCTIONAL_CLASS,
                                    "points": [
                                        {"lat": start[0], "lng": start[1]},
                                        {"lat": end[0], "lng": end[1]},
                                    ],
                                }
                            ]
                        },
                    },
                    "currentFlow": {
                        "speed": round(speed_kmh / 3.6, 6),
                        "speedUncapped": round(speed_kmh / 3.6, 6),
                        "freeFlow": round(free_flow_ms, 6),
                        "jamFactor": round(jam_factor, 2),
                        "confidence": SYNTHETIC_CONFIDENCE,
                        "traversability": "open",
                    },
                }
            )
        return {"sourceUpdated": self._timestamp(), "results": results}

    def incident_payload(self) -> dict[str, Any]:
        return {"sourceUpdated": self._timestamp(), "results": []}

    def _ordered_points(self) -> list[tuple[float, float]]:
        points = sorted(set(self._registry.values()))
        if len(points) >= 2:
            return points
        bbox = self._profile.bbox
        return [
            (bbox.south_west_lat, bbox.south_west_lon),
            (bbox.north_east_lat, bbox.north_east_lon),
        ]

    def _timestamp(self) -> str:
        return self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _distance_meters(start: tuple[float, float], end: tuple[float, float]) -> float:
        from motion.domain.geography import approximate_geo_distance_meters

        return round(approximate_geo_distance_meters(start, end), 1)


def build_offline_provider(
    profile: MapProfile,
    registry: Mapping[str, tuple[float, float]],
    *,
    random_source: random.Random | None = None,
    clock: Callable[[], datetime] | None = None,
) -> HereTrafficProvider:
    """Compose synthetic HERE DTOs with the production HERE parsing path."""

    payloads = HereCompatiblePayloadFactory(
        profile,
        registry,
        random_source=random_source,
        clock=clock,
    )
    fallback = (profile.geo_origin_lat, profile.geo_origin_lon)
    return HereTrafficProvider(
        flow_fetcher=SyntheticPayloadFetcher(payloads.flow_payload),
        incident_fetcher=SyntheticPayloadFetcher(payloads.incident_payload),
        traffic_parser=TrafficParser(fallback),
        incident_parser=IncidentParser(fallback),
    )
