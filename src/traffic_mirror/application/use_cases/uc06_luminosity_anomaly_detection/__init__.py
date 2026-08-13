"""UC-06: luminosity anomaly detection research direction."""

from ..descriptor import UseCaseDescriptor, UseCaseStatus

USE_CASE = UseCaseDescriptor(
    use_case_id="UC-06",
    name="Luminosity-Based Anomaly Detection",
    layer="Prediction",
    status=UseCaseStatus.NOT_IMPLEMENTED_RESEARCH_DIRECTION,
    goal="Use measured-versus-expected luminosity as context for safety, weather, traffic, and lighting anomalies.",
    actor="Automatic system",
    evidence=(
        "UC-06 proposes luminosity_delta and three qualitative correlations involving speed, anomalous traffic, weather, and lighting faults.",
        "The legacy classifier uses speed, throttle, brake, steering, and rain; it has no luminosity feature and does not implement UC-06 semantics.",
        "No repository module ingests lux values, builds an expected-luminosity baseline, or emits luminosity-derived anomalies.",
    ),
    dependencies=(
        "Luminosity sensor observations with time and location",
        "Seasonal and local expected-luminosity baseline",
        "Vehicle speed and traffic-anomaly observations",
        "Validated thresholds or anomaly model",
        "Smart-lighting, environmental-monitoring, vehicle-analysis, and safety ownership decision",
    ),
    missing_behavior=(
        "No lux schema, expected-value model, threshold, confidence, ground truth, or alert output contract is defined or implemented.",
        "The proposed rules do not distinguish normal night-time conditions, weather, shadows, artificial light, and equipment failure.",
    ),
    document_references=("MOTION / OR3 / UC-06",),
)

__all__ = ["USE_CASE"]
