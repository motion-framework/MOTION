"""UC-02's modification vocabulary.

Each kind is descriptive metadata attached to a ``ScenarioModification``; the
actual geometry edit happens externally (e.g. in JOSM). Only
``SPEED_LIMIT_CHANGE`` currently feeds a numeric parameter
(``modified_speed_limit_kmh``) back into domain policy
(``SpeedMirrorPolicy``); every other kind is descriptive only.
"""

from __future__ import annotations

from enum import StrEnum

from motion.domain.scenarios import ScenarioValidationError


class UC02ModificationKind(StrEnum):
    LANE_CLOSURE = "LANE_CLOSURE"
    ROAD_CLOSURE = "ROAD_CLOSURE"
    SPEED_LIMIT_CHANGE = "SPEED_LIMIT_CHANGE"
    SIGNAL_ADDED = "SIGNAL_ADDED"
    SIGNAL_REMOVED = "SIGNAL_REMOVED"
    EVENT_DIVERSION = "EVENT_DIVERSION"
    INCIDENT_SIMULATION = "INCIDENT_SIMULATION"


UC02_MODIFICATION_KINDS: tuple[str, ...] = tuple(kind.value for kind in UC02ModificationKind)


def validate_uc02_parameters(kind: str, modified_speed_limit_kmh: float | None) -> None:
    """Reject a scenario whose numeric parameter does not fit its kind.

    ``SPEED_LIMIT_CHANGE`` is the only kind that feeds a number into the
    simulation, so it requires ``modified_speed_limit_kmh``; without it the run
    would silently keep the baseline limit and compare the map against
    itself. Every other kind rejects the parameter, because applying a speed
    override to, say, a lane closure would mix two modifications into one
    KPI delta. Called before any map is provisioned.
    """

    if kind == UC02ModificationKind.SPEED_LIMIT_CHANGE and modified_speed_limit_kmh is None:
        raise ScenarioValidationError(
            "SPEED_LIMIT_CHANGE requires the new limit: pass --modified-speed-limit-kmh."
        )
    if kind != UC02ModificationKind.SPEED_LIMIT_CHANGE and modified_speed_limit_kmh is not None:
        raise ScenarioValidationError(
            f"--modified-speed-limit-kmh only applies to SPEED_LIMIT_CHANGE, not {kind}."
        )
