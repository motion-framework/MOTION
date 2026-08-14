# MOTION Macro Use-Case Catalog

This document records the seven MOTION macro use cases for vehicle analysis,
simulation, environmental monitoring and decision support. It distinguishes
observed repository behavior from research intent. Dedicated packages for
unavailable use cases contain traceability metadata only.

## Status meanings

- **IMPLEMENTED**: the core use-case workflow has direct, observable repository
  evidence.
- **PARTIALLY IMPLEMENTED**: reserved for a workflow whose use-case semantics
  are only partly delivered.
- **NOT IMPLEMENTED / RESEARCH DIRECTION**: documented intent with no matching
  application orchestration. Supporting code or similarly named ML code does
  not change this classification.
- **UNCLEAR**: reserved for cases where available evidence cannot establish a
  defensible status.

## Traceability matrix

| ID | Use case | Actor and goal | Repository evidence | Dependencies | Missing behavior | Status |
|---|---|---|---|---|---|---|
| UC-01 | Real-Time Traffic Mirroring | Automatic system; synchronize observed traffic with a CARLA traffic twin. | `motion.application.use_cases.uc01_real_time_traffic_mirroring` owns coverage, filtering and the tick loop; `motion.domain` owns population and speed policies; `motion.infrastructure.here` supplies flow/incidents; `motion.infrastructure.carla` owns world lifecycle, population and commands; `motion mirror` composes the workflow. | Device registry/feed, HERE Traffic, OSM/OpenDRIVE, CARLA/TrafficManager. | The governance dashboard is not evidenced. Current device readings are synthesized rather than ingested from a production field-device adapter. | **IMPLEMENTED**. |
| UC-02 | What-If Scenario Editor | Governance operator; compare a policy or infrastructure change with a real baseline. | UC-02 defines scenario types, but the repository contains neither an editor nor ScenarioRunner orchestration or delta-KPI comparison. | UC-01 baseline, scenario contract, CARLA ScenarioRunner, travel-time/density/emissions KPIs. | Area/scenario editing, repeatable execution, baseline comparison, and emissions calculation. | **NOT IMPLEMENTED / RESEARCH DIRECTION**. |
| UC-03 | Infrastructure Event Simulation | Urban planner/governance; compare effects of parking, ZTL, roundabout, or signal changes. | No infrastructure proposal model, before/after simulation, heatmap, or corridor comparison exists. | Traffic baseline, UC-02-like simulation, road demand, corridor and environmental KPIs. | Explicit flow and preconditions, simulation horizon, baseline rule, heatmaps, and a resolved CO2 method. | **NOT IMPLEMENTED / RESEARCH DIRECTION**. |
| UC-04 | Multivariate Traffic Prediction | Automatic system; forecast congestion, speed, traffic shape, and anomalies from heterogeneous features. | `motion.prediction` preserves a different legacy experiment: per-vehicle incident risk from speed, controls and rain. It does not create the UC-04 15-minute-to-24-hour network traffic forecasts. | Field/temporal/weather/HERE/history data, graph alignment, training, evaluation and persistence. | Feature matrix, history windows, forecast schema, spatial granularity, baselines, metrics, missing-data policy, and graph model. | **NOT IMPLEMENTED / RESEARCH DIRECTION**. |
| UC-05 | CO2 & Environmental Impact Forecast | Environmental governance; turn forecast traffic and weather into environmental risk and intervention options. | No CO2, air-quality, dispersion, or environmental-intervention forecast exists. Ownership and the choice between ML and vehicle-average estimation remain unresolved. | UC-04 forecasts, weather, validated emissions/air-quality model, UC-02, environmental monitoring and DSS. | Agreed owner and semantics, units, fleet/emission factors, dispersion, thresholds, validation, and choice of method. | **NOT IMPLEMENTED / RESEARCH DIRECTION**. |
| UC-06 | Luminosity-Based Anomaly Detection | Automatic system; use measured-minus-expected luminosity as safety, weather, traffic, or lighting context. | No lux ingestion or expected-luminosity model exists. The legacy model has no luminosity feature. | Lux observations, local/seasonal baseline, traffic observations, validated anomaly rules, cross-OR ownership. | Schema, baselines, thresholds, confidence, ground truth, disambiguation, and alert contract. | **NOT IMPLEMENTED / RESEARCH DIRECTION**. |
| UC-07 | Governance Alert & Recommendation Engine | Decision maker; receive auditable actions derived from validated forecasts. | The legacy script prints per-vehicle incident-risk alerts only. It does not implement governance rules, recommendations, channels, or approval workflows. | UC-04/05, event calendar, routing/rules, authorization/audit/notifications, UC-02 scenario contract. | Rule lifecycle and units, approval semantics, deduplication/escalation, dashboard/email/SMS/road-panel delivery, and CARLA pre-loading. | **NOT IMPLEMENTED / RESEARCH DIRECTION**. |

## Behavioral model scope

`motion.prediction` estimates the legacy per-vehicle
`incident_detected` label from speed, controls and simulated rain. It does not
produce network forecasts, luminosity anomalies or governance recommendations.
Its data and model limits are documented in the [model card](model-card.md).

## Cross-use-case dependencies

UC-01 supplies the baseline required by UC-02. UC-03 conceptually specializes
the infrastructure scenarios of UC-02; this dependency is inferred rather than
specified. UC-04 would provide forecasts to UC-05 and UC-07. UC-06 could become
a feature or alert input, but that integration is not specified. UC-05 also
depends on UC-02 for environmental what-if analysis, and UC-07 includes CARLA
scenario pre-loading.

These are conceptual dependencies inferred from the use-case descriptions; they
do not indicate implemented integrations between the dedicated packages.
