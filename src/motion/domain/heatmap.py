"""Pure UC-03 congestion-heatmap assembly.

Pairs real, observed HERE congestion with MOTION's own population-allocation
policy evaluated on the modified map, on the same 0-10 scale HERE already
uses for ``jam_factor``. See docs/scenario-kpis.md for what this heatmap
does and does not claim.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .population import JAM_DENSITY_VEH_PER_KM
from .traffic import TrafficSegment

CONGESTION_INDEX_MAX = 10.0


@dataclass(frozen=True, slots=True)
class CongestionCell:
    """One corridor segment's before/after congestion.

    ``before_congestion_index`` is the real HERE ``jam_factor`` (already on a
    0-10 scale). ``after_congestion_index`` is MOTION's own population
    allocation for the same segment evaluated against the modified map,
    converted back to that same jam-factor scale through the density formula
    the allocation itself uses (``count / length_km / JAM_DENSITY_VEH_PER_KM``).
    Both indices therefore express absolute congestion for one segment and are
    directly comparable. It is a policy prediction, not a per-vehicle CARLA
    measurement.
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
    jam_density_veh_per_km: float = JAM_DENSITY_VEH_PER_KM,
) -> CongestionHeatmap:
    """Pair each real segment with its policy-allocated vehicle count.

    ``before_segments`` and ``after_allocations`` must be the same length and
    in the same order: ``after_allocations[i]`` must describe
    ``before_segments[i]`` on the modified map.

    ``after_allocations`` must carry **per-segment** targets
    (``domain.population.segment_target_vehicle_count``), not counts already
    scaled down to a global simulator budget: a shared budget divided among
    the corridor's segments shrinks as the corridor gains segments, which
    would paint a wider corridor as less congested no matter what the
    scenario changed.
    """

    if jam_density_veh_per_km <= 0:
        raise ValueError("jam_density_veh_per_km must be positive")
    cells = tuple(
        CongestionCell(
            description=before.description,
            points=_points_of(before),
            before_congestion_index=min(CONGESTION_INDEX_MAX, max(0.0, before.jam_factor)),
            after_congestion_index=_after_index(after_segment, after_count, jam_density_veh_per_km),
        )
        for before, (after_segment, after_count) in zip(
            before_segments, after_allocations, strict=True
        )
    )
    return CongestionHeatmap(cells=cells)


def _after_index(
    segment: TrafficSegment, vehicle_count: int, jam_density_veh_per_km: float
) -> float:
    """Allocated vehicles for one segment, back on HERE's 0-10 jam scale.

    Inverts ``segment_target_vehicle_count``: that maps a jam factor to a
    density and then to a count over the segment's own length, so dividing the
    count by that length and by the jam-level density recovers the equivalent
    jam factor. A segment with no length carries no congestion.
    """

    length_km = segment.length_m / 1_000.0
    if length_km <= 0.0:
        return 0.0
    density_veh_per_km = vehicle_count / length_km
    index = (density_veh_per_km / jam_density_veh_per_km) * CONGESTION_INDEX_MAX
    return min(CONGESTION_INDEX_MAX, max(0.0, index))
