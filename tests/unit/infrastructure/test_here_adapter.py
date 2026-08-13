from __future__ import annotations

import json
from pathlib import Path

import pytest

from traffic_mirror.config.settings import load_settings
from traffic_mirror.domain.geography import BoundingBox
from traffic_mirror.domain.maps import MapProfile
from traffic_mirror.infrastructure.here.archive import HereArchive, verify_archive
from traffic_mirror.infrastructure.here.client import (
    HereApiError,
    HereEndpointFetcher,
    RequestsJsonTransport,
)
from traffic_mirror.infrastructure.here.factory import build_here_provider
from traffic_mirror.infrastructure.here.parser import IncidentParser, TrafficParser
from traffic_mirror.infrastructure.here.provider import HereTrafficProvider

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "here"


class FakeTransport:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def get_json(self, url, *, params, timeout_seconds):
        self.calls.append((url, dict(params), timeout_seconds))
        return self.payload


class FakeFetcher:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def fetch(self) -> dict:
        return self.payload


class FailingFetcher:
    def fetch(self) -> dict:
        raise RuntimeError("apiKey=must-not-appear")


class HttpErrorSession:
    def get(self, url, *, params, timeout):
        import requests

        del url, params, timeout
        response = requests.Response()
        response.status_code = 401
        raise requests.HTTPError(
            "401 at https://example.invalid?apiKey=must-not-appear",
            response=response,
        )


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_fetcher_builds_legacy_here_query_contract() -> None:
    transport = FakeTransport({"results": []})
    fetcher = HereEndpointFetcher(
        transport=transport,
        api_key="secret",
        bbox="bbox:1,2,3,4",
        url="https://example.invalid/flow",
        timeout_seconds=7,
        use_deep_coverage=True,
    )
    assert fetcher.fetch() == {"results": []}
    _, params, timeout = transport.calls[0]
    assert params == {
        "apiKey": "secret",
        "in": "bbox:1,2,3,4",
        "locationReferencing": "shape",
        "advancedFeatures": "deepCoverage",
    }
    assert timeout == 7


def test_provider_enriches_flow_with_incidents() -> None:
    provider = HereTrafficProvider(
        flow_fetcher=FakeFetcher(load("flow.json")),
        incident_fetcher=FakeFetcher(load("incidents.json")),
        traffic_parser=TrafficParser((40, 14)),
        incident_parser=IncidentParser((40, 14)),
    )
    segments = provider.fetch_segments()
    assert segments[0].incidents_nearby == 1
    assert segments[0].road_closure is True


def test_incident_failure_degrades_to_flow_without_logging_a_secret(caplog) -> None:
    provider = HereTrafficProvider(
        flow_fetcher=FakeFetcher(load("flow.json")),
        incident_fetcher=FailingFetcher(),
        traffic_parser=TrafficParser((40, 14)),
        incident_parser=IncidentParser((40, 14)),
    )

    segments = provider.fetch_segments()

    assert len(segments) == 2
    assert "RuntimeError" in caplog.text
    assert "must-not-appear" not in caplog.text


def test_http_error_never_exposes_the_credential_bearing_url() -> None:
    transport = RequestsJsonTransport(HttpErrorSession())

    with pytest.raises(HereApiError) as captured:
        transport.get_json(
            "https://example.invalid/flow",
            params={"apiKey": "must-not-appear"},
            timeout_seconds=1,
        )

    assert "HTTP 401" in str(captured.value)
    assert "must-not-appear" not in str(captured.value)


def test_provider_composition_is_offline_until_fetch_and_requires_a_key(tmp_path) -> None:
    profile = MapProfile(
        name="here",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        osm_path=tmp_path / "map.osm",
        xodr_path=tmp_path / "map.xodr",
    )
    configured = load_settings(root=tmp_path, environ={"HERE_API_KEY": "secret"})
    assert isinstance(build_here_provider(configured, profile), HereTrafficProvider)

    unconfigured = load_settings(root=tmp_path, environ={})
    with pytest.raises(HereApiError, match="HERE_API_KEY is empty"):
        build_here_provider(unconfigured, profile)


def test_archive_manifest_hashes_are_verifiable(tmp_path) -> None:
    archive = HereArchive.for_new_session(
        archive_root=tmp_path,
        map_name="test",
        bounding_box="bbox:1,2,3,4",
    )
    snapshot = archive.record("flow", load("flow.json"))
    verification = verify_archive(archive.session_directory)
    assert verification.valid
    assert verification.checked_snapshots == 1

    snapshot.write_text("tampered", encoding="utf-8")
    verification = verify_archive(archive.session_directory)
    assert not verification.valid
    assert "hash mismatch" in verification.errors[0]
