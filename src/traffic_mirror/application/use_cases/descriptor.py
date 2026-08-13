"""Typed metadata shared by the MOTION macro use-case packages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class UseCaseStatus(StrEnum):
    """Implementation status used in the MOTION macro-use-case catalog."""

    IMPLEMENTED = "IMPLEMENTED"
    PARTIALLY_IMPLEMENTED = "PARTIALLY IMPLEMENTED"
    NOT_IMPLEMENTED_RESEARCH_DIRECTION = "NOT IMPLEMENTED / RESEARCH DIRECTION"
    UNCLEAR = "UNCLEAR"


@dataclass(frozen=True)
class UseCaseDescriptor:
    """Traceability record for one documented MOTION macro use case."""

    use_case_id: str
    name: str
    layer: str
    status: UseCaseStatus
    goal: str
    actor: str
    evidence: tuple[str, ...]
    dependencies: tuple[str, ...]
    missing_behavior: tuple[str, ...]
    document_references: tuple[str, ...]
