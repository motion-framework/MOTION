from __future__ import annotations

import io

from motion.application.use_cases.uc01_real_time_traffic_mirroring.reporting import (
    ConsoleDashboardReporter,
    TickResult,
)
from motion.domain.devices import DeviceReading
from support.fakes import segment


def _tick() -> TickResult:
    return TickResult(
        timestamp=0.0,
        readings=(DeviceReading(device_id="SALERNO_001", count=9, speed=27.4),),
        segments=(segment(description="Via Roma"),),
        active_vehicle_count=34,
        target_vehicle_count=36,
        commanded_vehicle_count=34,
        repinned_vehicle_count=0,
        removed_vehicle_count=0,
    )


def _render(**reporter_options) -> str:
    stream = io.StringIO()
    ConsoleDashboardReporter(
        "salerno",
        device_registry={"SALERNO_001": (40.6768, 14.7581)},
        stream=stream,
        **reporter_options,
    ).report(_tick())
    return stream.getvalue()


def test_dashboard_labels_synthetic_device_readings_next_to_live_here_data() -> None:
    output = _render(traffic_source_label="HERE", device_source_label="SYNTHETIC")

    assert "FIELD DEVICES (SYNTHETIC):" in output
    assert "HERE FLOW ENRICHMENT:" in output
    assert "SALERNO_001" in output


def test_dashboard_labels_both_sources_in_offline_mode() -> None:
    output = _render(
        traffic_source_label="SYNTHETIC HERE-COMPATIBLE", device_source_label="SYNTHETIC"
    )

    assert "FIELD DEVICES (SYNTHETIC):" in output
    assert "SYNTHETIC HERE-COMPATIBLE FLOW ENRICHMENT:" in output


def test_dashboard_without_a_device_source_label_keeps_the_plain_heading() -> None:
    output = _render()

    assert "FIELD DEVICES:" in output
    assert "FIELD DEVICES (" not in output


def test_dashboard_reports_both_target_and_active_population() -> None:
    output = _render(device_source_label="SYNTHETIC")

    assert "Active vehicles: 34  |  Population target: 36" in output
