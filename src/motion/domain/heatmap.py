"""Pure UC-03 congestion-heatmap assembly.

Pairs real, observed HERE congestion with MOTION's own population-allocation
policy evaluated on the modified map, on the same 0-10 scale HERE already
uses for ``jam_factor``. See docs/scenario-kpis.md for what this heatmap
does and does not claim.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .population import MAX_VEHICLES_PER_SEGMENT
from .traffic import TrafficSegment

CONGESTION_INDEX_MAX = 10.0


@dataclass(frozen=True, slots=True)
class CongestionCell:
    """One corridor segment's before/after congestion.

    ``before_congestion_index`` is the real HERE ``jam_factor`` (already on a
    0-10 scale). ``after_congestion_index`` is MOTION's own population
    allocation (``domain.population.derive_population_targets``) for the same
    segment evaluated against the modified map, normalized to the same 0-10
    scale. It is a policy prediction, not a per-vehicle CARLA measurement.
    """

    description: str
    points: tuple[tuple[float, float], ...]
    before_congestion_index: float
    after_congestion_index: float


@dataclass(frozen=True, slots=True)
class CongestionHeatmap:
    cells: tuple[CongestionCell, ...]


def _points_of(segment: TrafficSegment) -> tuple[tuple[float, float], ...]:
    return segment.shape_points or ((segment.lat, segment.lon),)


def build_congestion_heatmap(
    before_segments: Sequence[TrafficSegment],
    after_allocations: Sequence[tuple[TrafficSegment, int]],
    *,
    max_vehicles_per_segment: int = MAX_VEHICLES_PER_SEGMENT,
) -> CongestionHeatmap:
    """Pair each real segment with its policy-allocated vehicle count.

    ``before_segments`` and ``after_allocations`` must be the same length and
    in the same order: ``after_allocations[i]`` must describe
    ``before_segments[i]`` on the modified map. This is what
    ``domain.population.derive_population_targets`` naturally preserves when
    called on the same ordered segment list.
    """

    if max_vehicles_per_segment <= 0:
        raise ValueError("max_vehicles_per_segment must be positive")
    cells = tuple(
        CongestionCell(
            description=before.description,
            points=_points_of(before),
            before_congestion_index=min(CONGESTION_INDEX_MAX, max(0.0, before.jam_factor)),
            after_congestion_index=min(
                CONGESTION_INDEX_MAX,
                max(0.0, (after_count / max_vehicles_per_segment) * CONGESTION_INDEX_MAX),
            ),
        )
        for before, (_after_segment, after_count) in zip(
            before_segments, after_allocations, strict=True
        )
    )
    return CongestionHeatmap(cells=cells)
