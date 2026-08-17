"""Shared offline fakes for UC-02/UC-03 application-level tests.

Adapted from ``tests/unit/application/test_uc01_service.py``'s private fakes
so scenario-service tests don't duplicate them; that file is left untouched.
"""

from __future__ import annotations

from motion.domain.traffic import TrafficSegment


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
    def __init__(self, readings=()):
        self.readings = list(readings)
        self.calls = 0

    def poll(self):
        self.calls += 1
        return list(self.readings)


class FakeSimulator:
    """Fake ``TrafficSimulator`` including the UC-02/UC-03 speed extension."""

    def __init__(self, *, average_speed_kmh: float | None = None):
        self.calls = []
        self.vehicle_count = 0
        self.closed = False
        self._average_speed_kmh = average_speed_kmh

    def owned_vehicle_count(self):
        return self.vehicle_count

    def average_speed_kmh(self):
        return self._average_speed_kmh

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
