"""Traffic and field-observation ports."""

from __future__ import annotations

from typing import Protocol

from motion.domain.devices import DeviceReading
from motion.domain.traffic import TrafficSegment


class TrafficDataProvider(Protocol):
    def fetch_segments(self) -> list[TrafficSegment]: ...


class FieldDeviceProvider(Protocol):
    def poll(self) -> list[DeviceReading]: ...
