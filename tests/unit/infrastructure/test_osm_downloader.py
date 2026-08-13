from __future__ import annotations

from pathlib import Path

import pytest

from traffic_mirror.domain.geography import BoundingBox
from traffic_mirror.infrastructure.osm.downloader import (
    OsmDownloader,
    OsmDownloadError,
    RetryableOsmError,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "maps" / "minimal.osm"


class SequenceTransport:
    def __init__(self, outcomes: list[bytes | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str, str, float]] = []

    def get(self, url, *, params, headers, timeout_seconds):
        self.calls.append((url, params["bbox"], headers["User-Agent"], timeout_seconds))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_downloader_fails_over_then_atomically_writes_valid_osm(tmp_path) -> None:
    transport = SequenceTransport([RetryableOsmError("temporary"), FIXTURE.read_bytes()])
    sleeps: list[float] = []
    output = tmp_path / "maps" / "area.osm"
    downloader = OsmDownloader(
        endpoints=("https://first.invalid", "https://second.invalid"),
        contact_email="research@example.invalid",
        timeout_seconds=12,
        transport=transport,
        retry_delay_seconds=0.25,
        sleeper=sleeps.append,
    )

    assert downloader.download(BoundingBox(40, 14, 40.01, 14.01), output) == output
    assert output.read_bytes() == FIXTURE.read_bytes()
    assert [call[0] for call in transport.calls] == [
        "https://first.invalid",
        "https://second.invalid",
    ]
    assert transport.calls[0][1] == "14,40,14.01,40.01"
    assert "research@example.invalid" in transport.calls[0][2]
    assert sleeps == [0.25]
    assert not output.with_suffix(".osm.tmp").exists()


def test_existing_extract_is_not_downloaded_without_overwrite(tmp_path) -> None:
    output = tmp_path / "area.osm"
    output.write_bytes(FIXTURE.read_bytes())
    transport = SequenceTransport([])
    downloader = OsmDownloader(
        endpoints=("https://unused.invalid",),
        contact_email="research@example.invalid",
        transport=transport,
    )

    assert downloader.download(BoundingBox(40, 14, 40.01, 14.01), output) == output
    assert transport.calls == []


def test_malformed_overpass_payload_is_not_persisted(tmp_path) -> None:
    output = tmp_path / "area.osm"
    downloader = OsmDownloader(
        endpoints=("https://malformed.invalid",),
        contact_email="research@example.invalid",
        transport=SequenceTransport([b"<html>not osm</html>"]),
    )

    with pytest.raises(OsmDownloadError, match="instead of <osm>"):
        downloader.download(BoundingBox(40, 14, 40.01, 14.01), output)

    assert not output.exists()
