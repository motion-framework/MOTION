"""Composite HERE flow/incident provider used by UC-01."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from motion.domain.traffic import (
    TrafficSegment,
    enrich_segments_with_incidents,
)

from .parser import IncidentParser, TrafficParser

LOGGER = logging.getLogger(__name__)


class PayloadFetcher(Protocol):
    def fetch(self) -> dict[str, Any]: ...


class HereTrafficProvider:
    def __init__(
        self,
        *,
        flow_fetcher: PayloadFetcher,
        incident_fetcher: PayloadFetcher,
        traffic_parser: TrafficParser,
        incident_parser: IncidentParser,
    ) -> None:
        self._flow_fetcher = flow_fetcher
        self._incident_fetcher = incident_fetcher
        self._traffic_parser = traffic_parser
        self._incident_parser = incident_parser

    def fetch_segments(self) -> list[TrafficSegment]:
        segments = self._traffic_parser.parse(self._flow_fetcher.fetch())
        try:
            incidents = self._incident_parser.parse(self._incident_fetcher.fetch())
        except Exception as error:
            # UC-01 historically degrades to flow-only when the incident endpoint
            # fails. Preserve that contract without logging a credential-bearing
            # request URL: the exception type is sufficient operational context.
            LOGGER.warning(
                "HERE incident acquisition failed; continuing with flow only (cause=%s)",
                type(error).__name__,
            )
            incidents = []
        return enrich_segments_with_incidents(segments, incidents)
