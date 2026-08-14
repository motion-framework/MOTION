"""UC-05: environmental-impact forecast research direction."""

from ..descriptor import UseCaseDescriptor, UseCaseStatus

USE_CASE = UseCaseDescriptor(
    use_case_id="UC-05",
    name="CO2 & Environmental Impact Forecast",
    layer="Prediction",
    status=UseCaseStatus.NOT_IMPLEMENTED_RESEARCH_DIRECTION,
    goal="Relate forecast traffic and weather to environmental risk and potential governance interventions.",
    actor="Environmental governance",
    evidence=(
        "UC-05 proposes a time-banded risk map, threshold alerts, and a dynamic limited-traffic-zone recommendation.",
        "Ownership by MOTION environmental monitoring and the choice between ML and vehicle-average calculation remain unresolved.",
        "No repository module forecasts CO2, air quality, dispersion, or environmental intervention impact.",
    ),
    dependencies=(
        "UC-04 vehicle-count and speed forecasts",
        "Weather observations and forecasts",
        "Validated emissions or air-quality model and thresholds",
        "UC-02 for environmental what-if comparison",
        "MOTION environmental-monitoring and decision-support components",
    ),
    missing_behavior=(
        "Ownership between vehicle analysis, environmental monitoring, and decision support is unresolved.",
        "UC-05 conflates CO2 concentration, vehicle emissions, and general air quality and does not settle ML versus deterministic estimation.",
        "No units, fleet composition, emission factors, dispersion model, thresholds, or validation method are implemented.",
    ),
    document_references=("MOTION / OR3 / UC-05",),
)

__all__ = ["USE_CASE"]
