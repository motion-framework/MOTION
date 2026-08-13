"""UC-02: what-if scenario editor research direction."""

from ..descriptor import UseCaseDescriptor, UseCaseStatus

USE_CASE = UseCaseDescriptor(
    use_case_id="UC-02",
    name="What-If Scenario Editor",
    layer="Simulation",
    status=UseCaseStatus.NOT_IMPLEMENTED_RESEARCH_DIRECTION,
    goal="Compare infrastructure or policy changes with a real traffic baseline before real-world deployment.",
    actor="Governance operator",
    evidence=(
        "UC-02 specifies editable closures, speed limits, signals, event diversions, and incidents.",
        "Repository archaeology found current-state mirroring but no scenario editor, CARLA ScenarioRunner orchestration, or baseline-versus-scenario KPI comparison.",
    ),
    dependencies=(
        "UC-01 real traffic baseline",
        "Scenario definition and validation contract",
        "CARLA ScenarioRunner integration",
        "Travel-time, density, and emissions KPI calculation",
    ),
    missing_behavior=(
        "No area-selection or scenario-editing application service exists.",
        "No scenario execution, repeatability policy, or delta-KPI result model exists.",
        "No implemented emissions-estimation method is evidenced.",
    ),
    document_references=("MOTION / OR3 / UC-02",),
)

__all__ = ["USE_CASE"]
