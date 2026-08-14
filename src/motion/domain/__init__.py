"""Technology-independent MOTION domain models and policies."""

from .geography import BoundingBox
from .maps import MapProfile
from .traffic import TrafficIncident, TrafficSegment

__all__ = [
    "BoundingBox",
    "MapProfile",
    "TrafficIncident",
    "TrafficSegment",
]
