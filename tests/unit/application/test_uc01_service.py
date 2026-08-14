from __future__ import annotations

import unittest
from pathlib import Path

from motion.application.use_cases.uc01_real_time_traffic_mirroring.coverage import (
    MapCoverage,
)
from motion.application.use_cases.uc01_real_time_traffic_mirroring.filtering import (
    SegmentFilter,
)
from motion.application.use_cases.uc01_real_time_traffic_mirroring.service import (
    TrafficMirrorService,
)
from motion.domain.devices import DeviceReading
from motion.domain.geography import BoundingBox
from motion.domain.maps import MapProfile
from motion.domain.mirroring import SpeedMirrorPolicy
from motion.domain.traffic import TrafficSegment


class IdentityProjector:
    def to_xy(self, latitude_deg: float, longitude_deg: float):
        return latitude_deg, longitude_deg


class FakeTrafficProvider:
    def __init__(self, segments=None, error: Exception | None = None):
        self.segments = list(segments or [])
        self.error = error
        self.calls = 0

    def fetch_segments(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.segments)


class FakeDeviceProvider:
    def __init__(self, readings):
        self.readings = list(readings)
        self.calls = 0

    def poll(self):
        self.calls += 1
        return list(self.readings)


class CapturingReporter:
    def __init__(self):
        self.results = []

    def report(self, result):
        self.results.append(result)


class FakeSimulator:
    def __init__(self):
        self.calls = []
        self.vehicle_count = 0
        self.closed = False

    def owned_vehicle_count(self):
        return self.vehicle_count

    def synchronize_population(self, targets):
        targets = tuple(targets)
        self.calls.append(("segment_population", targets))
        target = sum(item.target_count for item in targets)
        self.vehicle_count = target
        return target

    def synchronize_uniform_population(self, target_count, anchors):
        self.calls.append(("uniform_population", target_count, tuple(anchors)))
        self.vehicle_count = target_count
        return target_count

    def apply_segment_commands(self, commands, fallback_command):
        commands = tuple(commands)
        self.calls.append(("commands", commands, fallback_command))
        return self.vehicle_count

    def repin_to_road(self, coverages):
        self.calls.append(("repin", tuple(coverages)))
        return self.vehicle_count if coverages else 0

    def set_mirrored_coverage(self, coverages):
        self.calls.append(("coverage", tuple(coverages)))

    def sanitize_tick(self):
        self.calls.append(("sanitize_tick",))
        return 0

    def sanitize_watchdog(self):
        self.calls.append(("sanitize_watchdog",))
        return 0

    def focus_view(self, anchors):
        self.calls.append(("focus", tuple(anchors)))

    def close(self):
        self.calls.append(("close",))
        self.closed = True


def segment(**changes):
    values = {
        "description": "Via Test",
        "length_m": 999.0,
        "speed_kmh": 20.0,
        "free_kmh": 40.0,
        "jam_factor": 5.0,
        "confidence": 0.9,
        "shape_points": ((10.0, 10.0), (10.0, 110.0)),
        "functional_class": 4,
    }
    values.update(changes)
    return TrafficSegment(**values)


class TrafficMirrorServiceTest(unittest.TestCase):
    def setUp(self):
        self.profile = MapProfile(
            name="test_map",
            bbox=BoundingBox(0.0, 0.0, 50.0, 120.0),
            osm_path=Path("test.osm"),
            xodr_path=Path("test.xodr"),
            device_registry={"D1": (20.0, 20.0)},
        )
        self.coverage = MapCoverage(self.profile, IdentityProjector())

    def make_service(self, traffic_provider, device_provider, simulator, reporter):
        return TrafficMirrorService(
            traffic_provider=traffic_provider,
            device_provider=device_provider,
            simulator=simulator,
            coverage=self.coverage,
            speed_policy=SpeedMirrorPolicy(50.0),
            reporter=reporter,
            wall_clock=lambda: 123.0,
        )

    def test_tick_orchestrates_segment_population_commands_and_reporting(self):
        provider = FakeTrafficProvider([segment()])
        devices = FakeDeviceProvider([DeviceReading("D1", 10, 30.0, 1.0)])
        simulator = FakeSimulator()
        reporter = CapturingReporter()
        service = self.make_service(provider, devices, simulator, reporter)

        result = service.run_tick()

        # 100 m inside map * 60 veh/km at jam factor 5 = 6 vehicles.
        self.assertEqual(result.target_vehicle_count, 6)
        self.assertEqual(result.active_vehicle_count, 6)
        self.assertEqual(result.commanded_vehicle_count, 6)
        population_call = simulator.calls[0]
        self.assertEqual(population_call[0], "segment_population")
        self.assertEqual(population_call[1][0].target_count, 6)
        command_call = simulator.calls[1]
        mirrored_command = command_call[1][0].command
        self.assertEqual(mirrored_command.target_speed_kmh, 20.0)
        self.assertEqual(mirrored_command.follow_distance_meters, 2.0)
        self.assertEqual(reporter.results, [result])

    def test_closure_command_preserves_stop_and_increased_gap(self):
        provider = FakeTrafficProvider([segment(road_closure=True)])
        service = self.make_service(
            provider,
            FakeDeviceProvider([]),
            FakeSimulator(),
            CapturingReporter(),
        )

        service.run_tick()
        command = service._simulator.calls[1][1][0].command

        self.assertEqual(command.target_speed_kmh, 0.0)
        self.assertEqual(command.follow_distance_meters, 8.0)
        self.assertTrue(command.is_held_at_closure)

    def test_flow_failure_uses_device_population_and_fallback_command(self):
        provider = FakeTrafficProvider(error=RuntimeError("apiKey=must-not-appear-in-logs"))
        devices = FakeDeviceProvider([DeviceReading("D1", 10, 29.0, 1.0)])
        simulator = FakeSimulator()
        service = self.make_service(provider, devices, simulator, CapturingReporter())

        with self.assertLogs(
            "motion.application.use_cases.uc01_real_time_traffic_mirroring.service",
            level="WARNING",
        ) as captured:
            result = service.run_tick()

        self.assertEqual(result.target_vehicle_count, 50)
        uniform = simulator.calls[0]
        self.assertEqual(uniform[0], "uniform_population")
        self.assertEqual(uniform[2], ((20.0, 20.0),))
        commands = simulator.calls[1]
        self.assertEqual(commands[1], ())
        self.assertEqual(commands[2].target_speed_kmh, 40.0)
        warning = "\n".join(captured.output)
        self.assertIn("FakeTrafficProvider", warning)
        self.assertIn("RuntimeError", warning)
        self.assertNotIn("must-not-appear-in-logs", warning)

    def test_empty_segments_use_device_population_and_fallback_command(self):
        provider = FakeTrafficProvider([])
        devices = FakeDeviceProvider([DeviceReading("D1", 8, 31.0, 1.0)])
        simulator = FakeSimulator()
        service = self.make_service(provider, devices, simulator, CapturingReporter())

        result = service.run_tick()

        self.assertEqual(result.target_vehicle_count, 40)
        uniform = simulator.calls[0]
        self.assertEqual(uniform, ("uniform_population", 40, ((20.0, 20.0),)))
        commands = simulator.calls[1]
        self.assertEqual(commands[1], ())
        self.assertEqual(commands[2].target_speed_kmh, 40.0)

    def test_prepare_primes_segment_anchors_and_focuses_view(self):
        provider = FakeTrafficProvider([segment()])
        simulator = FakeSimulator()
        service = self.make_service(
            provider, FakeDeviceProvider([]), simulator, CapturingReporter()
        )

        anchors = service.prepare()

        self.assertEqual(provider.calls, 1)
        self.assertEqual(anchors, ((10.0, 10.0), (10.0, 110.0), (20.0, 20.0)))
        self.assertEqual(simulator.calls[0][0], "focus")

    def test_road_filter_falls_back_to_all_segments_when_no_match(self):
        filter_policy = SegmentFilter(road_filter="missing")
        values = [segment(description="A"), segment(description="B")]
        filtered = filter_policy.apply(
            values,
            coverage=self.coverage,
            device_points=((20.0, 20.0),),
        )
        self.assertEqual(filtered, values)

    def test_close_is_explicit_and_idempotent(self):
        simulator = FakeSimulator()
        service = self.make_service(
            FakeTrafficProvider([]),
            FakeDeviceProvider([]),
            simulator,
            CapturingReporter(),
        )
        service.close()
        service.close()
        self.assertTrue(simulator.closed)
        self.assertEqual(simulator.calls, [("close",)])

    def test_watchdog_runs_immediately_then_once_per_second_until_deadline(self):
        now = [10.0]
        simulator = FakeSimulator()
        service = TrafficMirrorService(
            traffic_provider=FakeTrafficProvider([]),
            device_provider=FakeDeviceProvider([]),
            simulator=simulator,
            coverage=self.coverage,
            speed_policy=SpeedMirrorPolicy(50.0),
            monotonic_clock=lambda: now[0],
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
        )

        service.watch_until(12.5)

        watchdog_calls = [call for call in simulator.calls if call[0] == "sanitize_watchdog"]
        self.assertEqual(len(watchdog_calls), 4)
        self.assertEqual(now[0], 12.5)


if __name__ == "__main__":
    unittest.main()
