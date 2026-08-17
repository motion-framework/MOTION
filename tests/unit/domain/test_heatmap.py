from __future__ import annotations

import pytest

from motion.domain.heatmap import CONGESTION_INDEX_MAX, build_congestion_heatmap
from motion.domain.traffic import TrafficSegment


def _segment(**overrides):
    values = {
        "description": "seg",
        "length_m": 500.0,
        "speed_kmh": 30.0,
        "free_kmh": 40.0,
        "jam_factor": 6.0,
        "confidence": 1.0,
        "lat": 40.0,
        "lon": 14.0,
    }
    values.update(overrides)
    return TrafficSegment(**values)


def test_build_congestion_heatmap_pairs_segments_in_order() -> None:
    a = _segment(description="A", jam_factor=6.0)
    b = _segment(description="B", jam_factor=2.0)

    heatmap = build_congestion_heatmap([a, b], [(a, 20), (b, 0)], max_vehicles_per_segment=40)

    assert [cell.description for cell in heatmap.cells] == ["A", "B"]
    assert heatmap.cells[0].before_congestion_index == pytest.approx(6.0)
    assert heatmap.cells[0].after_congestion_index == pytest.approx(5.0)
    assert heatmap.cells[1].before_congestion_index == pytest.approx(2.0)
    assert heatmap.cells[1].after_congestion_index == pytest.approx(0.0)


def test_build_congestion_heatmap_uses_segment_points_or_lat_lon_fallback() -> None:
    with_shape = _segment(shape_points=((1.0, 2.0), (3.0, 4.0)))
    without_shape = _segment(lat=5.0, lon=6.0)

    heatmap = build_congestion_heatmap(
        [with_shape, without_shape], [(with_shape, 0), (without_shape, 0)]
    )

    assert heatmap.cells[0].points == ((1.0, 2.0), (3.0, 4.0))
    assert heatmap.cells[1].points == ((5.0, 6.0),)


def test_after_congestion_index_is_clamped_at_the_scale_maximum() -> None:
    segment = _segment()

    heatmap = build_congestion_heatmap([segment], [(segment, 1000)], max_vehicles_per_segment=40)

    assert heatmap.cells[0].after_congestion_index == CONGESTION_INDEX_MAX


def test_before_congestion_index_is_clamped_to_the_valid_range() -> None:
    segment = _segment(jam_factor=15.0)

    heatmap = build_congestion_heatmap([segment], [(segment, 0)])

    assert heatmap.cells[0].before_congestion_index == CONGESTION_INDEX_MAX


def test_before_congestion_index_clamps_negative_values_to_zero() -> None:
    segment = _segment(jam_factor=-3.0)

    heatmap = build_congestion_heatmap([segment], [(segment, 0)])

    assert heatmap.cells[0].before_congestion_index == 0.0


def test_mismatched_lengths_are_rejected() -> None:
    segment = _segment()

    with pytest.raises(ValueError):
        build_congestion_heatmap([segment, segment], [(segment, 0)])


def test_non_positive_max_vehicles_per_segment_is_rejected() -> None:
    segment = _segment()

    with pytest.raises(ValueError):
        build_congestion_heatmap([segment], [(segment, 0)], max_vehicles_per_segment=0)
