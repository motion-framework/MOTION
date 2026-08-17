from __future__ import annotations

import pytest

from motion.domain.scenarios import (
    ScenarioModification,
    ScenarioStatus,
    ScenarioValidationError,
    validate_modification_kind,
)


def test_scenario_modification_requires_a_non_empty_kind() -> None:
    with pytest.raises(ScenarioValidationError):
        ScenarioModification(kind="")
    with pytest.raises(ScenarioValidationError):
        ScenarioModification(kind="   ")


def test_scenario_modification_rejects_non_positive_speed_limit() -> None:
    with pytest.raises(ScenarioValidationError):
        ScenarioModification(kind="SPEED_LIMIT_CHANGE", modified_speed_limit_kmh=0.0)
    with pytest.raises(ScenarioValidationError):
        ScenarioModification(kind="SPEED_LIMIT_CHANGE", modified_speed_limit_kmh=-10.0)


def test_scenario_modification_accepts_a_positive_speed_limit() -> None:
    modification = ScenarioModification(kind="SPEED_LIMIT_CHANGE", modified_speed_limit_kmh=30.0)

    assert modification.modified_speed_limit_kmh == 30.0


def test_validate_modification_kind_accepts_allowed_values() -> None:
    assert validate_modification_kind("A", ("A", "B")) == "A"


def test_validate_modification_kind_rejects_unknown_values() -> None:
    with pytest.raises(ScenarioValidationError):
        validate_modification_kind("C", ("A", "B"))


def test_scenario_status_values() -> None:
    assert ScenarioStatus.STAGED == "STAGED"
    assert ScenarioStatus.READY == "READY"
    assert ScenarioStatus.SIMULATED == "SIMULATED"
