"""Application service for UC-01 real-time traffic mirroring."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from motion.domain.geography import Point2D
from motion.domain.mirroring import (
    MAXIMUM_VEHICLE_COUNT,
    SpeedMirrorPolicy,
    derive_target_vehicle_count,
)
from motion.domain.population import derive_population_targets
from motion.domain.traffic import TrafficSegment
from motion.ports.simulator import (
    PopulationTarget,
    SegmentCommand,
    SegmentCoverage,
    TrafficSimulator,
)
from motion.ports.traffic import FieldDeviceProvider, TrafficDataProvider

from .coverage import MapCoverage
from .filtering import SegmentFilter
from .reporting import NullTickReporter, TickReporter, TickResult

WATCHDOG_INTERVAL_SECONDS = 1.0
logger = logging.getLogger(__name__)


class TrafficMirrorService:
    """Coordinate one complete mirror tick through explicit collaborators."""

    def __init__(
        self,
        *,
        traffic_provider: TrafficDataProvider,
        device_provider: FieldDeviceProvider,
        simulator: TrafficSimulator,
        coverage: MapCoverage,
        speed_policy: SpeedMirrorPolicy,
        segment_filter: SegmentFilter | None = None,
        reporter: TickReporter | None = None,
        update_interval_seconds: float = 60.0,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._traffic_provider = traffic_provider
        self._device_provider = device_provider
        self._simulator = simulator
        self._coverage = coverage
        self._speed_policy = speed_policy
        self._segment_filter = segment_filter or SegmentFilter()
        self._reporter = reporter or NullTickReporter()
        self._update_interval_seconds = update_interval_seconds
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._sleep = sleep
        self._device_points = coverage.device_anchor_points()
        self._last_segment_anchor_points: tuple[Point2D, ...] = ()
        self._closed = False

    def prepare(self) -> tuple[Point2D, ...]:
        """Prime coverage anchors before the first population tick.

        The extra fetch is a deliberate compatibility behavior: the legacy
        pipeline fetched HERE once while centering/preparing coverage and then
        again at the first tick.
        """

        segments = self._filter_segments(self._fetch_segments_or_empty())
        coverages = self._coverages_inside_map(segments)
        if coverages:
            self._last_segment_anchor_points = tuple(
                point for segment_coverage in coverages for point in segment_coverage.points_xy
            )
            self._simulator.focus_view(self._last_segment_anchor_points)
        return self.coverage_anchor_points

    @property
    def coverage_anchor_points(self) -> tuple[Point2D, ...]:
        return self._last_segment_anchor_points + self._device_points

    def run_tick(self) -> TickResult:
        if self._closed:
            raise RuntimeError("TrafficMirrorService is closed")

        readings = tuple(self._device_provider.poll())
        segments = self._filter_segments(self._fetch_segments_or_empty())
        coverages = self._coverages_inside_map(segments)

        if coverages:
            self._last_segment_anchor_points = tuple(
                point for segment_coverage in coverages for point in segment_coverage.points_xy
            )
            target_vehicle_count = self._synchronize_by_segment(coverages)
        else:
            target_vehicle_count = derive_target_vehicle_count(readings)
            self._simulator.synchronize_uniform_population(
                target_vehicle_count, self.coverage_anchor_points
            )

        commands = tuple(
            SegmentCommand(
                coverage=segment_coverage,
                command=self._speed_policy.command_for(segment_coverage.segment),
            )
            for segment_coverage in coverages
        )
        commanded_count = self._simulator.apply_segment_commands(
            commands, self._speed_policy.fallback_command()
        )
        repinned_count = self._simulator.repin_to_road(coverages)
        self._simulator.set_mirrored_coverage(coverages)
        removed_count = self._simulator.sanitize_tick()

        result = TickResult(
            timestamp=self._wall_clock(),
            readings=readings,
            segments=tuple(segments),
            active_vehicle_count=self._simulator.owned_vehicle_count(),
            target_vehicle_count=target_vehicle_count,
            commanded_vehicle_count=commanded_count,
            repinned_vehicle_count=repinned_count,
            removed_vehicle_count=removed_count,
        )
        self._reporter.report(result)
        return result

    def _synchronize_by_segment(self, coverages: list[SegmentCoverage]) -> int:
        population_coverages = [
            self._coverage.resized_for_population(segment_coverage)
            for segment_coverage in coverages
        ]
        allocations = derive_population_targets(
            [segment_coverage.segment for segment_coverage in population_coverages],
            MAXIMUM_VEHICLE_COUNT,
        )
        targets = tuple(
            PopulationTarget(coverage=segment_coverage, target_count=count)
            for segment_coverage, (_segment, count) in zip(
                population_coverages, allocations, strict=True
            )
        )
        return self._simulator.synchronize_population(targets)

    def _fetch_segments_or_empty(self) -> list[TrafficSegment]:
        try:
            return self._traffic_provider.fetch_segments()
        except Exception as error:
            # Flow acquisition has an intentional availability fallback: UC-01
            # keeps the simulator alive and uses uniform device-derived state.
            logger.warning(
                "HERE traffic acquisition failed; using device-derived "
                "uniform population (provider=%s, cause=%s)",
                type(self._traffic_provider).__name__,
                exception_type_chain(error),
            )
            return []

    def _filter_segments(self, segments: list[TrafficSegment]) -> list[TrafficSegment]:
        return self._segment_filter.apply(
            segments,
            coverage=self._coverage,
            device_points=self._device_points,
        )

    def _coverages_inside_map(self, segments: list[TrafficSegment]) -> list[SegmentCoverage]:
        return self._coverage.coverages_of(self._coverage.segments_touching_map(segments))

    def watch_until(self, deadline: float) -> int:
        removed_count = 0
        while True:
            removed_count += self._simulator.sanitize_watchdog()
            remaining_seconds = deadline - self._monotonic_clock()
            if remaining_seconds <= 0.0:
                return removed_count
            self._sleep(min(WATCHDOG_INTERVAL_SECONDS, remaining_seconds))

    def run_forever(self, *, stop_requested: Callable[[], bool] | None = None) -> None:
        should_stop = stop_requested or (lambda: False)
        try:
            self.prepare()
            while not should_stop():
                tick_started_at = self._monotonic_clock()
                self.run_tick()
                self.watch_until(tick_started_at + self._update_interval_seconds)
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._simulator.close()

    def __enter__(self) -> TrafficMirrorService:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()


def exception_type_chain(error: BaseException) -> str:
    """Return root-cause type names without leaking URLs, tokens or payloads."""

    names: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.append(type(current).__name__)
        current = current.__cause__ or current.__context__
    return " <- ".join(names)
