"""UC-03: infrastructure event simulation."""

from ..descriptor import UseCaseDescriptor, UseCaseStatus

USE_CASE = UseCaseDescriptor(
    use_case_id="UC-03",
    name="Infrastructure Event Simulation",
    layer="Simulation",
    status=UseCaseStatus.IMPLEMENTED,
    goal="Evaluate traffic and environmental effects of proposed urban infrastructure changes.",
    actor="Urban planner / governance",
    evidence=(
        "motion.application.use_cases.uc03_infrastructure_event_simulation.service."
        "InfrastructureEventService implements the same stage -> apply -> simulate flow as "
        "UC-02 (sharing application.scenario_workflow), plus a before/after congestion heatmap "
        "assembled from real HERE segments and MOTION's own population-allocation policy "
        "(motion.domain.heatmap.build_congestion_heatmap), rendered to a PNG via "
        "motion.infrastructure.reporting.heatmap (optional 'viz' extra).",
        "motion.domain.kpi supplies the same measured baseline/scenario KPI snapshots as "
        "UC-02 for corridor travel time, density and an area CO2 estimate.",
        "The installed motion CLI exposes 'infra-event stage', 'infra-event apply' and "
        "'infra-event simulate', each independently testable offline via fakes/fixtures.",
    ),
    dependencies=(
        "A validated real traffic baseline, supplied by the same HERE-based proposal UC-01/"
        "UC-02 use",
        "The shared application.scenario_workflow pipeline (also used by UC-02)",
        "An external OSM editor (e.g. JOSM) for the human infrastructure-edit step",
        "CARLA simulator and TrafficManager for the modified-map simulation",
        "The optional 'viz' (matplotlib) extra for heatmap image rendering",
    ),
    missing_behavior=(
        "Map editing is performed in an external tool (e.g. JOSM), not an in-app editor.",
        "The modified-map simulation reuses UC-01's own population/speed-mirroring loop "
        "instead of driving the separate CARLA ScenarioRunner framework -- a deliberate "
        "architecture substitution, not a missing capability (see the package README).",
        "The heatmap's 'after' state is MOTION's own population-allocation policy applied to "
        "the modified map's coverage, not a per-vehicle CARLA measurement; since MOTION's "
        "domain model is bbox/speed-limit-level rather than lane/junction-topology-level, "
        "parking/ZTL/roundabout changes move the heatmap only to the extent CARLA's own "
        "TrafficManager reacts to the modified OpenDRIVE topology at simulation time.",
        "The CO2 estimate is a flat average-passenger-car approximation "
        "(grams per vehicle-km), not a validated fleet-composition emissions model.",
    ),
    document_references=("MOTION / OR3 / UC-03",),
)

__all__ = ["USE_CASE"]
