"""UC-03's modification vocabulary.

Each kind is descriptive metadata attached to a ``ScenarioModification``; the
actual infrastructure edit happens externally (e.g. in JOSM). None of these
kinds currently feed a numeric parameter back into domain policy -- unlike
UC-02's ``SPEED_LIMIT_CHANGE``, MOTION's domain model has no lane/parking/
junction-type representation, so their effect on measured KPIs is realized
only through CARLA's own simulation of the modified OpenDRIVE topology.
"""

from __future__ import annotations

from enum import StrEnum


class UC03ModificationKind(StrEnum):
    NEW_PARKING = "NEW_PARKING"
    ZTL_EXTENDED = "ZTL_EXTENDED"
    ROUNDABOUT_VS_SIGNAL = "ROUNDABOUT_VS_SIGNAL"


UC03_MODIFICATION_KINDS: tuple[str, ...] = tuple(kind.value for kind in UC03ModificationKind)
