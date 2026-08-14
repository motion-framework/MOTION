"""UC-04: multivariate traffic prediction research direction."""

from ..descriptor import UseCaseDescriptor, UseCaseStatus

USE_CASE = UseCaseDescriptor(
    use_case_id="UC-04",
    name="Multivariate Traffic Prediction",
    layer="Prediction",
    status=UseCaseStatus.NOT_IMPLEMENTED_RESEARCH_DIRECTION,
    goal="Forecast short- and medium-term traffic from field, temporal, weather, HERE, and historical features.",
    actor="Automatic system",
    evidence=(
        "UC-04 proposes 15-minute-to-24-hour congestion, speed, traffic-shape, and anomaly forecasts.",
        "motion.prediction preserves a legacy per-vehicle incident-risk classifier from speed, controls, and rain; it does not implement the UC-04 traffic forecast semantics.",
        "No repository code builds the UC-04 multivariate feature matrix, graph history, forecast horizons, or traffic forecast outputs.",
    ),
    dependencies=(
        "Field count, speed, CO2, and luminosity observations",
        "Temporal calendar and historical traffic windows",
        "External weather and HERE Traffic data",
        "Road-graph alignment, model training, evaluation, and persistence",
    ),
    missing_behavior=(
        "No forecast target schema, spatial granularity, accuracy baseline, or acceptance metric is defined or implemented.",
        "No heterogeneous data synchronization, missing-data policy, or graph construction is implemented.",
        "The model family remains open, and Traffic4cast data does not contain the proposed heterogeneous features.",
    ),
    document_references=("MOTION / OR3 / UC-04",),
)

__all__ = ["USE_CASE"]
