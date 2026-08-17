"""UC-02's modification vocabulary.

Each kind is descriptive metadata attached to a ``ScenarioModification``; the
actual geometry edit happens externally (e.g. in JOSM). Only
``SPEED_LIMIT_CHANGE`` currently feeds a numeric parameter
(``modified_speed_limit_kmh``) back into domain policy
(``SpeedMirrorPolicy``); every other kind is descriptive only.
"""

from __future__ import annotations

from enum import StrEnum


class UC02ModificationKind(StrEnum):
    LANE_CLOSURE = "LANE_CLOSURE"
    ROAD_CLOSURE = "ROAD_CLOSURE"
    SPEED_LIMIT_CHANGE = "SPEED_LIMIT_CHANGE"
    SIGNAL_ADDED = "SIGNAL_ADDED"
    SIGNAL_REMOVED = "SIGNAL_REMOVED"
    EVENT_DIVERSION = "EVENT_DIVERSION"
    INCIDENT_SIMULATION = "INCIDENT_SIMULATION"


UC02_MODIFICATION_KINDS: tuple[str, ...] = tuple(kind.value for kind in UC02ModificationKind)
