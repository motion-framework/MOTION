"""UC-03: infrastructure event simulation research direction."""

from ..descriptor import UseCaseDescriptor, UseCaseStatus

USE_CASE = UseCaseDescriptor(
    use_case_id="UC-03",
    name="Infrastructure Event Simulation",
    layer="Simulation",
    status=UseCaseStatus.NOT_IMPLEMENTED_RESEARCH_DIRECTION,
    goal="Evaluate traffic and environmental effects of proposed urban infrastructure changes.",
    actor="Urban planner / governance",
    evidence=(
        "UC-03 covers parking access, extended limited-traffic zones, and roundabout-versus-signal comparisons.",
        "The repository contains no infrastructure proposal model, before/after simulation orchestration, congestion heatmap, or corridor comparison service.",
    ),
    dependencies=(
        "A validated traffic baseline, conceptually supplied by UC-01",
        "Scenario simulation capability, conceptually overlapping UC-02",
        "Road-network and demand models",
        "Corridor and environmental KPI definitions",
    ),
    missing_behavior=(
        "UC-03 does not define a flow, explicit precondition, simulation horizon, or baseline-selection rule.",
        "No infrastructure-event simulation or before/after visualization is implemented.",
        "The proposed vehicle CO2 estimation method is unresolved.",
    ),
    document_references=("MOTION / OR3 / UC-03",),
)

__all__ = ["USE_CASE"]
