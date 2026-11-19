"""UC-02: what-if scenario editor."""

from ..descriptor import UseCaseDescriptor, UseCaseStatus

USE_CASE = UseCaseDescriptor(
    use_case_id="UC-02",
    name="What-If Scenario Editor",
    layer="Simulation",
    status=UseCaseStatus.IMPLEMENTED,
    goal="Compare infrastructure or policy changes with a real traffic baseline before real-world deployment.",
    actor="Governance operator",
    evidence=(
        "motion.application.use_cases.uc02_what_if_scenario.service.WhatIfScenarioService "
        "implements stage -> apply -> simulate: HERE-based road proposal and baseline "
        "provisioning (reusing application.road_selection and MapProvisioningService), an "
        "externally-edited map ingestion step with change detection, and a modified-map "
        "simulation that reuses UC-01's own TrafficMirrorService/CarlaTrafficSimulator.",
        "motion.domain.kpi computes a baseline KPI snapshot directly from real HERE segments "
        "and a scenario snapshot from measured post-simulation vehicle count/average speed "
        "(TrafficSimulator.average_speed_kmh); motion.domain.kpi.KpiDelta reports the delta.",
        "The installed motion CLI exposes 'scenario stage', 'scenario apply' and "
        "'scenario simulate', each independently testable offline via fakes/fixtures.",
    ),
    dependencies=(
        "UC-01 real traffic baseline and its provisioning/mirroring machinery",
        "HERE Traffic flow data for road proposal and baseline KPI computation",
        "An external OSM editor (e.g. JOSM) for the human map-edit step",
        "CARLA simulator and TrafficManager for the modified-map simulation",
    ),
    missing_behavior=(
        "Map editing is performed in an external tool (e.g. JOSM), not an in-app editor; "
        "MOTION stages, ingests and converts the edited file but does not author geometry.",
        "The modified-map simulation reuses UC-01's own population/speed-mirroring loop "
        "instead of driving the separate CARLA ScenarioRunner framework -- a deliberate "
        "architecture substitution, not a missing capability (see the package README).",
        "Effects of road-topology changes (closures, diversions) on measured KPIs depend on "
        "CARLA's own TrafficManager pathfinding on the modified OpenDRIVE map at simulation "
        "time; MOTION's own domain model is bbox/speed-limit-level, not topology-level.",
    ),
    document_references=("MOTION / OR3 / UC-02",),
)

__all__ = ["USE_CASE"]
