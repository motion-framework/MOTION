"""Download and validate OSM extracts from configured Overpass mirrors."""

from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from traffic_mirror.domain.geography import BoundingBox

RETRYABLE_HTTP_STATUS_CODES = frozenset({502, 503, 504})


class OsmDownloadError(RuntimeError):
    pass


class BytesTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> bytes: ...


class RequestsBytesTransport:
    def get(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> bytes:
        try:
            import requests
        except ImportError as error:  # pragma: no cover
            raise OsmDownloadError("The 'requests' package is required.") from error
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return response.content
        except requests.HTTPError as error:
            status = getattr(error.response, "status_code", None)
            if status in RETRYABLE_HTTP_STATUS_CODES:
                raise RetryableOsmError(f"Overpass returned HTTP {status}") from error
            raise OsmDownloadError(f"Overpass rejected the request (HTTP {status}).") from error
        except requests.Timeout as error:
            raise RetryableOsmError("Overpass request timed out.") from error
        except requests.RequestException as error:
            raise RetryableOsmError("Overpass network request failed.") from error


class RetryableOsmError(OsmDownloadError):
    pass


class OsmDownloader:
    def __init__(
        self,
        *,
        endpoints: Sequence[str],
        contact_email: str,
        timeout_seconds: float = 180.0,
        transport: BytesTransport | None = None,
        retry_delay_seconds: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not contact_email:
            raise OsmDownloadError(
                "OSM_DOWNLOADER_CONTACT_EMAIL is required by public Overpass etiquette."
            )
        if not endpoints:
            raise OsmDownloadError("No Overpass endpoints are configured.")
        self._endpoints = tuple(endpoints)
        self._contact_email = contact_email
        self._timeout_seconds = timeout_seconds
        self._transport = transport or RequestsBytesTransport()
        self._retry_delay_seconds = retry_delay_seconds
        self._sleeper = sleeper

    def download(
        self,
        bbox: BoundingBox,
        destination_path: Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        if destination_path.exists() and not overwrite:
            return destination_path
        headers = {
            "Accept": "application/xml",
            "User-Agent": (f"MOTION/0.1 (contact: {self._contact_email})"),
        }
        last_error: RetryableOsmError | None = None
        for endpoint in self._endpoints:
            try:
                content = self._transport.get(
                    endpoint,
                    params={"bbox": bbox.to_overpass_bbox()},
                    headers=headers,
                    timeout_seconds=self._timeout_seconds,
                )
                _validate_osm(content)
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination_path.with_suffix(destination_path.suffix + ".tmp")
                temporary.write_bytes(content)
                os.replace(temporary, destination_path)
                return destination_path
            except RetryableOsmError as error:
                last_error = error
                self._sleeper(self._retry_delay_seconds)
        raise OsmDownloadError("Every configured Overpass mirror failed.") from last_error


def _validate_osm(content: bytes) -> None:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise OsmDownloadError("Overpass returned malformed XML.") from error
    if root.tag != "osm":
        raise OsmDownloadError(f"Overpass returned <{root.tag}> instead of <osm>.")
