from __future__ import annotations

import pytest

from motion.domain.heatmap import CONGESTION_INDEX_MAX, build_congestion_heatmap
from motion.domain.population import segment_target_vehicle_count
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

    heatmap = build_congestion_heatmap([a, b], [(a, 20), (b, 0)])

    assert [cell.description for cell in heatmap.cells] == ["A", "B"]
    assert heatmap.cells[0].before_congestion_index == pytest.approx(6.0)
    # 20 vehicles over 0.5 km is 40 veh/km; jam level is 120 veh/km -> 3.33/10.
    assert heatmap.cells[0].after_congestion_index == pytest.approx(40.0 / 120.0 * 10.0)
    assert heatmap.cells[1].before_congestion_index == pytest.approx(2.0)
    assert heatmap.cells[1].after_congestion_index == pytest.approx(0.0)


def test_unchanged_allocation_reproduces_the_before_index() -> None:
    """The after index inverts the allocation, so an unchanged map shows no change.

    Anything else would paint a difference the scenario did not cause -- which
    is what dividing a globally-budgeted count by the per-segment cap used to
    do, shrinking every segment as the corridor gained segments.
    """

    # jam * 6 vehicles on a 500 m segment, so these stay under the 40-vehicle
    # per-segment cap; rounding to whole vehicles costs at most 0.2 of an index.
    segments = [_segment(jam_factor=jam, length_m=500.0) for jam in (0.0, 3.0, 6.0)]
    allocations = [(s, segment_target_vehicle_count(s)) for s in segments]

    heatmap = build_congestion_heatmap(segments, allocations)

    for cell in heatmap.cells:
        assert cell.after_congestion_index == pytest.approx(cell.before_congestion_index, abs=0.2)


def test_after_index_is_clipped_once_the_per_segment_cap_binds() -> None:
    """Above the cap the allocation cannot represent the real jam level.

    A 500 m segment at jam 9 wants 54 vehicles but may only have 40, so the
    predicted index reads lower than the observed one. The heatmap understates
    congestion there rather than inventing capacity it cannot simulate.
    """

    segment = _segment(jam_factor=9.0, length_m=500.0)
    allocation = segment_target_vehicle_count(segment)

    heatmap = build_congestion_heatmap([segment], [(segment, allocation)])

    assert allocation == 40
    assert heatmap.cells[0].after_congestion_index < heatmap.cells[0].before_congestion_index


def test_after_index_is_independent_of_how_many_segments_the_corridor_has() -> None:
    one = _segment(jam_factor=6.0, length_m=500.0)
    allocation = segment_target_vehicle_count(one)

    narrow = build_congestion_heatmap([one], [(one, allocation)])
    wide = build_congestion_heatmap([one] * 40, [(one, allocation)] * 40)

    assert wide.cells[0].after_congestion_index == pytest.approx(
        narrow.cells[0].after_congestion_index
    )


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

    heatmap = build_congestion_heatmap([segment], [(segment, 1000)])

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


def test_non_positive_jam_density_is_rejected() -> None:
    segment = _segment()

    with pytest.raises(ValueError):
        build_congestion_heatmap([segment], [(segment, 0)], jam_density_veh_per_km=0)


def test_zero_length_segment_carries_no_congestion() -> None:
    segment = _segment(length_m=0.0)

    heatmap = build_congestion_heatmap([segment], [(segment, 10)])

    assert heatmap.cells[0].after_congestion_index == 0.0
