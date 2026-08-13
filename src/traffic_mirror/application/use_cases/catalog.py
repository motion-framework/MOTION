"""Ordered catalog of the seven documented MOTION macro use cases."""

from __future__ import annotations

from .descriptor import UseCaseDescriptor
from .uc01_real_time_traffic_mirroring import USE_CASE as UC_01
from .uc02_what_if_scenario import USE_CASE as UC_02
from .uc03_infrastructure_event_simulation import USE_CASE as UC_03
from .uc04_multivariate_traffic_prediction import USE_CASE as UC_04
from .uc05_environmental_impact_forecast import USE_CASE as UC_05
from .uc06_luminosity_anomaly_detection import USE_CASE as UC_06
from .uc07_governance_alerts import USE_CASE as UC_07

USE_CASE_CATALOG: tuple[UseCaseDescriptor, ...] = (
    UC_01,
    UC_02,
    UC_03,
    UC_04,
    UC_05,
    UC_06,
    UC_07,
)

__all__ = ["USE_CASE_CATALOG"]
