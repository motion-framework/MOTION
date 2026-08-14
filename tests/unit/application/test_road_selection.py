from __future__ import annotations

import pytest

from motion.application.road_selection import (
    RoadSelectionError,
    build_map_state_for_road,
    choose_road_interactively,
    group_by_road,
    representative_segment,
    segments_near_center,
    select_main_road_segment,
)
from motion.config.paths import ProjectPaths
from motion.domain.traffic import TrafficSegment


def _segment(**overrides: object) -> TrafficSegment:
    values: dict[str, object] = {
        "description": "Via A",
        "length_m": 100.0,
        "speed_kmh": 20.0,
        "free_kmh": 40.0,
        "jam_factor": 5.0,
        "confidence": 0.9,
        "lat": 40.0,
        "lon": 14.0,
        "shape_points": ((40.0, 14.0), (40.001, 14.0)),
        "functional_class": 3,
    }
    values.update(overrides)
    return TrafficSegment(**values)  # type: ignore[arg-type]


def test_grouping_and_representative_selection_preserve_observable_order() -> None:
    first = _segment(speed_kmh=10.0, jam_factor=2.0, lat=40.0)
    second = _segment(speed_kmh=30.0, jam_factor=6.0, lat=40.002)
    other = _segment(description="Via B", lat=40.01)

    roads = group_by_road([other, first, second])

    assert [road.name for road in roads] == ["Via A", "Via B"]
    assert roads[0].average_speed_kmh == 20.0
    assert roads[0].average_jam_factor == 4.0
    assert representative_segment(roads[0].segments, (40.0018, 14.0)) is second
    with pytest.raises(RoadSelectionError, match="empty road"):
        representative_segment([], (40.0, 14.0))


def test_geographic_ranking_prefers_reliable_named_urban_coverage() -> None:
    center = (40.0, 14.0)
    motorway = _segment(
        description="Autostrada",
        functional_class=1,
        shape_points=((40.0001, 14.0), (40.0002, 14.0)),
    )
    unknown = _segment(description="unknown", shape_points=((40.0001, 14.0),))
    low_confidence = _segment(
        description="Via Low",
        confidence=0.4,
        shape_points=((40.0001, 14.0),),
    )
    selected_near = _segment(
        description="Via Selected",
        shape_points=((40.001, 14.0), (40.0015, 14.0)),
    )
    selected_far = _segment(
        description="Via Selected",
        shape_points=((40.002, 14.0), (40.0025, 14.0)),
    )
    outside = _segment(
        description="Outside",
        shape_points=((40.02, 14.0), (40.021, 14.0)),
    )

    near = segments_near_center(
        [motorway, unknown, low_confidence, selected_near, selected_far, outside],
        center,
    )
    assert outside not in near
    assert select_main_road_segment(near, center) is selected_near
    with pytest.raises(RoadSelectionError, match="No HERE segment"):
        select_main_road_segment([], center)


@pytest.mark.parametrize("value", ["0", "-1", "3", "invalid"])
def test_interactive_selection_rejects_values_outside_displayed_contract(value) -> None:
    roads = group_by_road([_segment(), _segment(description="Via B")])
    with pytest.raises(RoadSelectionError):
        choose_road_interactively(roads, input_reader=lambda _prompt: value)


def test_interactive_selection_accepts_one_based_index_and_quit() -> None:
    roads = group_by_road([_segment(), _segment(description="Via B")])
    assert choose_road_interactively(roads, input_reader=lambda _prompt: "2").name == "Via B"
    with pytest.raises(KeyboardInterrupt):
        choose_road_interactively(roads, input_reader=lambda _prompt: "q")


def test_selected_road_builds_managed_state_and_four_devices(tmp_path) -> None:
    paths = ProjectPaths.discover(tmp_path)
    state, selected = build_map_state_for_road(
        segment=_segment(
            shape_points=(
                (40.0, 14.0),
                (40.001, 14.0),
                (40.002, 14.0),
                (40.003, 14.0),
            )
        ),
        radius_meters=70.0,
        map_name="research-road",
        project_paths=paths,
    )

    assert state.source == "here-road-selection"
    assert state.geo_filter is True
    assert state.anchor_functional_class == 3
    assert len(state.device_registry) == 4
    assert state.osm_path == "data/maps/research-road/research-road.osm"
    assert len(selected.shape_points) == 4


def test_selected_road_requires_geometry(tmp_path) -> None:
    with pytest.raises(RoadSelectionError, match="no geometry"):
        build_map_state_for_road(
            segment=_segment(shape_points=()),
            radius_meters=100.0,
            map_name="empty",
            project_paths=ProjectPaths.discover(tmp_path),
        )
