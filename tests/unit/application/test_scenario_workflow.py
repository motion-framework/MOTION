from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from motion.application import scenario_workflow
from motion.application.map_provisioning import ProvisioningResult
from motion.config.paths import ProjectPaths, validate_scenario_id
from motion.config.settings import load_settings
from motion.domain.geography import BoundingBox
from motion.domain.maps import MapProfile
from motion.domain.traffic import TrafficSegment
from motion.ports.maps import MapArtifactProcessingResult, MapRepairOutcome

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class FakeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_json(self, url, *, params, timeout_seconds):
        self.calls.append((url, params, timeout_seconds))
        return self.payload


class FakeProvisioningService:
    def __init__(self):
        self.received_states = []

    def provision(self, state):
        self.received_states.append(state)
        return ProvisioningResult(
            state=state,
            osm_path=Path("unused.osm"),
            xodr_path=Path("unused.xodr"),
            reused_osm=False,
            zero_length_repair=MapRepairOutcome(0, None),
            object_overflow_repair=MapRepairOutcome(0, None),
            remaining_degenerate_geometries=0,
            remaining_object_overflows=0,
        )


def _here_settings(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(
        "motion.infrastructure.here.client.RequestsJsonTransport",
        lambda *args, **kwargs: FakeTransport(payload),
    )
    return load_settings(root=tmp_path, environ={"HERE_API_KEY": "test-key"})


def _single_segment_payload(center: tuple[float, float]) -> dict:
    """A minimal, valid HERE flow payload with real geometry near ``center``.

    Purpose-built (rather than the shared ``fixtures/here/flow.json``, which
    intentionally includes a shapeless fallback segment for other tests) so
    road selection always has real geometry to anchor a map on.
    """

    lat, lon = center
    return {
        "sourceUpdated": "2026-01-01T00:00:00Z",
        "results": [
            {
                "currentFlow": {
                    "speed": 10.0,
                    "freeFlow": 15.0,
                    "jamFactor": 3.0,
                    "confidence": 0.9,
                },
                "location": {
                    "description": "Via Baseline",
                    "length": 200.0,
                    "shape": {
                        "links": [
                            {
                                "functionalClass": 4,
                                "points": [
                                    {"lat": lat, "lng": lon},
                                    {"lat": lat + 0.001, "lng": lon},
                                    {"lat": lat + 0.002, "lng": lon},
                                ],
                            }
                        ]
                    },
                },
            }
        ],
    }


def test_propose_and_provision_baseline_geo_mode(tmp_path, monkeypatch) -> None:
    settings = _here_settings(tmp_path, monkeypatch, _single_segment_payload((40.0005, 14.0000)))
    fake_service = FakeProvisioningService()
    monkeypatch.setattr(
        scenario_workflow, "build_map_provisioning_service", lambda _settings: fake_service
    )

    proposal = scenario_workflow.propose_and_provision_baseline(
        settings=settings,
        lat=40.0005,
        lon=14.0000,
        radius_meters=200.0,
        map_name="salerno",
        geo=True,
    )

    assert proposal.state.name == "salerno"
    assert proposal.segment.description
    assert fake_service.received_states == [proposal.state]
    assert 20 <= proposal.estimated_vehicle_count <= 80
    assert len(proposal.device_readings) == len(proposal.state.device_registry)


def test_propose_and_provision_baseline_interactive_mode(tmp_path, monkeypatch) -> None:
    settings = _here_settings(tmp_path, monkeypatch, _single_segment_payload((40.0005, 14.0000)))
    monkeypatch.setattr(
        scenario_workflow,
        "build_map_provisioning_service",
        lambda _settings: FakeProvisioningService(),
    )
    prompts: list[str] = []

    def input_reader(prompt: str) -> str:
        prompts.append(prompt)
        return "1"

    proposal = scenario_workflow.propose_and_provision_baseline(
        settings=settings,
        lat=40.0005,
        lon=14.0000,
        radius_meters=200.0,
        map_name="interactive",
        geo=False,
        input_reader=input_reader,
    )

    assert prompts
    assert proposal.state.name == "interactive"


def test_propose_and_provision_baseline_rejects_non_positive_radius(tmp_path, monkeypatch) -> None:
    settings = _here_settings(tmp_path, monkeypatch, _single_segment_payload((40.0, 14.0)))

    with pytest.raises(ValueError, match="radius_meters must be positive"):
        scenario_workflow.propose_and_provision_baseline(
            settings=settings, lat=40.0, lon=14.0, radius_meters=0.0, map_name="x", geo=True
        )


def test_propose_and_provision_baseline_requires_here_segments(tmp_path, monkeypatch) -> None:
    settings = _here_settings(tmp_path, monkeypatch, {"sourceUpdated": "now", "results": []})

    with pytest.raises(ValueError, match="no traffic segments"):
        scenario_workflow.propose_and_provision_baseline(
            settings=settings, lat=40.0, lon=14.0, radius_meters=200.0, map_name="x", geo=True
        )


def test_stage_editable_copy_creates_a_sibling_map_without_touching_active_state(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    profile = MapProfile(
        name="salerno",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        osm_path=paths.map_osm_path("salerno"),
        xodr_path=paths.map_xodr_path("salerno"),
    )
    profile.osm_path.parent.mkdir(parents=True)
    shutil.copy2(FIXTURES / "maps" / "minimal.osm", profile.osm_path)

    editable_path, digest = scenario_workflow.stage_editable_copy(profile, "sid-1", paths)

    assert editable_path == paths.map_osm_path(paths.scenario_map_name("salerno", "sid-1"))
    assert editable_path.read_bytes() == profile.osm_path.read_bytes()
    assert digest == scenario_workflow.sha256_of(profile.osm_path)
    assert not paths.active_map_state.exists()


def test_scenario_map_converter_reuses_converter_and_artifact_processor() -> None:
    calls = []

    class FakeConverter:
        def convert(self, profile):
            calls.append(("convert", profile.name))
            return profile.xodr_path

    class FakeArtifactProcessor:
        def repair_and_validate(self, path):
            calls.append(("repair", path))
            return MapArtifactProcessingResult(
                zero_length_repair=MapRepairOutcome(0, None),
                object_overflow_repair=MapRepairOutcome(0, None),
                remaining_degenerate_geometries=0,
                remaining_object_overflows=0,
            )

        def osm_covers(self, path, bbox):  # pragma: no cover - unused by convert_and_repair
            raise AssertionError("osm_covers must not be called by ScenarioMapConverter")

    converter = scenario_workflow.ScenarioMapConverter(
        converter=FakeConverter(), artifact_processor=FakeArtifactProcessor()
    )
    profile = MapProfile(
        name="variant",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        osm_path=Path("variant.osm"),
        xodr_path=Path("variant.xodr"),
    )

    result = converter.convert_and_repair(profile)

    assert calls == [("convert", "variant"), ("repair", Path("variant.xodr"))]
    assert result.remaining_degenerate_geometries == 0


def test_frozen_traffic_provider_replays_the_same_snapshot() -> None:
    segment = TrafficSegment(
        description="seg",
        length_m=10.0,
        speed_kmh=10.0,
        free_kmh=20.0,
        jam_factor=1.0,
        confidence=1.0,
    )
    provider = scenario_workflow.FrozenTrafficProvider([segment])

    first = provider.fetch_segments()
    second = provider.fetch_segments()

    assert first == second == [segment]
    first.append("mutation")  # returned lists must be independent copies
    assert provider.fetch_segments() == [segment]


def test_generate_scenario_id_is_filesystem_safe_and_stable_format() -> None:
    scenario_id = scenario_workflow.generate_scenario_id(clock=lambda: 1_700_000_000.0)

    assert validate_scenario_id(scenario_id) == scenario_id
    assert scenario_id.startswith("2023")
