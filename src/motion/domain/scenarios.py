"""Pure value objects shared by the UC-02/UC-03 scenario workflow.

Domain modules perform no I/O; the actual map edit happens in an external
tool (for example JOSM). This module only models the metadata MOTION itself
needs to track a scenario through staging, conversion and simulation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class ScenarioValidationError(ValueError):
    pass


class ScenarioStatus(StrEnum):
    """Lifecycle of a UC-02/UC-03 scenario record."""

    STAGED = "STAGED"
    READY = "READY"
    SIMULATED = "SIMULATED"


@dataclass(frozen=True, slots=True)
class ScenarioModification:
    """The governance operator's declared intent for one scenario.

    ``kind`` is validated against the calling use case's own vocabulary
    (``UC02ModificationKind``/``UC03ModificationKind``); this module stays
    use-case-neutral. Only a speed-limit change currently feeds a numeric
    parameter back into domain policy (``SpeedMirrorPolicy``); every other
    kind is carried purely as descriptive metadata because the actual
    geometry edit happens externally.
    """

    kind: str
    notes: str = ""
    modified_speed_limit_kmh: float | None = None

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ScenarioValidationError("A scenario modification kind is required.")
        if self.modified_speed_limit_kmh is not None and self.modified_speed_limit_kmh <= 0:
            raise ScenarioValidationError("modified_speed_limit_kmh must be positive.")


def validate_modification_kind(kind: str, allowed: Sequence[str]) -> str:
    """Return ``kind`` unchanged if it belongs to ``allowed``, else raise."""

    if kind not in allowed:
        allowed_text = ", ".join(allowed)
        raise ScenarioValidationError(f"{kind!r} is not one of the supported kinds: {allowed_text}")
    return kind
