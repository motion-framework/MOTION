"""UC-07: governance alert and recommendation research direction."""

from ..descriptor import UseCaseDescriptor, UseCaseStatus

USE_CASE = UseCaseDescriptor(
    use_case_id="UC-07",
    name="Governance Alert & Recommendation Engine",
    layer="Prediction",
    status=UseCaseStatus.NOT_IMPLEMENTED_RESEARCH_DIRECTION,
    goal="Translate validated traffic and environmental forecasts into auditable governance alerts and recommendations.",
    actor="Decision maker",
    evidence=(
        "UC-07 gives example rules for congestion, CO2, event-related demand, dashboard delivery, messaging, road panels, and CARLA pre-loading.",
        "The legacy behavioral-analysis script prints per-vehicle incident-risk alerts; it does not implement governance rules, recommendations, channels, or decision workflows.",
        "No repository module evaluates the UC-07 governance rules or integrates dashboard, email, SMS, or road-panel channels.",
    ),
    dependencies=(
        "Validated UC-04 traffic forecasts",
        "Validated UC-05 environmental forecasts",
        "Event calendar, routing, and configurable rule data",
        "Decision-support authorization, audit, and notification services",
        "UC-02/CARLA scenario contract for pre-loading a validation scenario",
    ),
    missing_behavior=(
        "No rule configuration, units, provider scales, versioning, audit, approval, deduplication, escalation, or channel delivery exists.",
        "UC-07 does not resolve whether the decision maker receives, approves, or executes each recommendation.",
        "Email/SMS delivery and CARLA pre-loading remain uncommitted research requirements.",
    ),
    document_references=("MOTION / OR3 / UC-07",),
)

__all__ = ["USE_CASE"]
