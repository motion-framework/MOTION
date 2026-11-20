# UC-02/UC-03 scenario KPI methodology

## Scope

This document covers `motion.domain.kpi` and `motion.domain.heatmap`, the
shared math behind UC-02's delta-KPI report and UC-03's corridor KPIs plus
congestion heatmap. Both packages call the same functions through
`application.scenario_workflow`; see each package's own README
(`src/motion/application/use_cases/uc02_what_if_scenario/README.md`,
`.../uc03_infrastructure_event_simulation/README.md`) for the command-level
walkthrough. This document is the methodology reference the use-case catalog
points to.

## Baseline snapshot: real, not simulated

The baseline `KpiSnapshot` (`domain.kpi.snapshot_from_segments`) is computed
directly from real HERE traffic segments fetched once at `simulate` time (live
or, with `--offline`, the same synthetic HERE-compatible provider `motion
mirror --offline` uses). No simulation is required for the baseline: this
matches UC-02's own precondition, "UC-01 active / real baseline available."

- Vehicle count reuses `domain.population.derive_population_targets` --
  the exact jam-factor-to-density formula UC-01 itself uses to populate
  CARLA, **including its global `MAXIMUM_VEHICLE_COUNT` budget** -- so the
  baseline count is what UC-01 would actually mirror for this traffic. The
  budget matters: summing uncapped per-segment targets would put the baseline
  above the population ceiling the scenario side is physically bound by, and
  every density and CO2 delta would then be measuring that ceiling instead of
  the scenario. Note the ceiling binds both sides on a busy corridor, so
  those two KPIs move only when the modified map actually costs the simulator
  vehicles (spawn failures, culled actors), not merely because traffic is
  heavy.
- Travel time is the time to traverse the **whole corridor**: the sum of each
  segment's own crossing time (`length_m / speed_kmh`). It has to be, because
  the scenario side crosses that same total `distance_km` at the measured
  speed -- a mean of per-segment times would describe one average segment and
  could not be differenced against it.
- Density is total vehicle count over total corridor length.
- CO2 is `vehicle_count * distance_km * grams_per_vehicle_km` (see below).

## Fairness: the same traffic snapshot on both sides

`application.scenario_workflow.FrozenTrafficProvider` fetches HERE segments
**once** and replays that fixed snapshot for both the baseline computation
and the modified-map simulation. This is a deliberate choice: two independent
live fetches could observe different real traffic conditions a few seconds
apart, which would make "before" and "after" not actually comparable. Fetch
once, replay twice.

## Scenario snapshot: measured, not a policy echo

The scenario `KpiSnapshot` (`domain.kpi.snapshot_from_measured`) is built from
what the simulator actually observed after running UC-01's own
`TrafficMirrorService` against the modified map for the requested tick count:

- `TrafficSimulator.owned_vehicle_count()` -- session-owned, live vehicles.
- `TrafficSimulator.average_speed_kmh()` -- a new port method, implemented in
  `CarlaTrafficSimulator` by averaging the existing
  `infrastructure.carla.kinematics.vehicle_speed_kmh` helper over every owned
  live actor; `None` when no vehicle is owned.

Both are read immediately after the tick loop completes and before the
simulator closes (which destroys session-owned actors), so this is a genuine
post-simulation measurement, not an echo of the `SpeedMirrorPolicy` commands
issued during the tick. `None`/zero vehicles is reported as an all-zero
snapshot rather than an infinite travel time, since there is nothing to
measure.

## What actually moves the measured numbers

MOTION's own domain model is bbox- and speed-limit-level; it has no lane,
parking or junction-topology representation. This has a direct, honest
consequence for what a modification kind can change:

- **UC-02's `SPEED_LIMIT_CHANGE`** is the one modification kind that feeds a
  domain parameter directly: `--modified-speed-limit-kmh` (required for this
  kind and rejected for every other) replaces the
  modified map's `speed_limit_kmh`, which `SpeedMirrorPolicy` reads when
  commanding vehicles. Its effect on the measured KPIs is real and
  analytically explainable.
- **Every other modification kind** -- lane/road closure, signal add/remove,
  event diversion, incident simulation (UC-02); new parking, extended ZTL,
  roundabout-vs-signal (UC-03) -- is recorded as descriptive metadata only.
  Its effect on the *measured* corridor KPIs depends entirely on how CARLA's
  own TrafficManager reacts to the modified OpenDRIVE road network at
  simulation time (rerouting, actors being culled by
  `OutsideCoverageRule` if a covered segment's geometry no longer matches,
  and so on) -- an emergent property of a live CARLA run, not something
  MOTION computes analytically. Live CARLA execution is outside this
  repository's offline test gate, exactly as for every other CARLA-touching
  path in UC-01 (see [non-regression.md](non-regression.md)); the code path
  is exercised end-to-end by the offline test suite through fakes, and is
  otherwise "code path preserved, live environment unverified."

## UC-03's congestion heatmap: policy-predicted, not measured

`domain.heatmap.build_congestion_heatmap` pairs, for each real corridor
segment:

- `before_congestion_index`: the real HERE `jam_factor` (already 0-10).
- `after_congestion_index`: MOTION's own population-allocation policy
  (`domain.population.segment_target_vehicle_count`, the per-segment half of
  what UC-01's mirroring loop performs) applied to the same frozen segment
  against the modified map's coverage, converted back onto HERE's 0-10 scale
  by inverting that same formula (`count / length_km / JAM_DENSITY_VEH_PER_KM`).
  UC-01's *global* vehicle budget is deliberately excluded here: it shares one
  fixed ceiling among however many segments the corridor has, so including it
  would make every segment look calmer purely because the corridor is wide,
  and would not be comparable with the absolute jam factor on the "before"
  side. The one place the two scales still part company is a segment whose
  demand exceeds the 40-vehicle per-segment cap: there the prediction
  understates congestion rather than inventing capacity CARLA cannot simulate.

This is explicitly a **policy prediction**, not a per-vehicle CARLA
measurement -- unlike the aggregate corridor KPIs above, which are measured.
Because the modified map's bounding box and device registry are inherited
unchanged from the baseline, and MOTION's coverage/allocation math depends
only on bbox and jam factor (not on lanes, parking or junction type), the
heatmap's "after" state is *identical* to "before" for most modification
kinds -- the conversion above inverts the allocation exactly below the
per-segment cap. That is an accurate reflection of what this coarse domain
model can predict analytically, not a defect; a visible difference means a
segment genuinely left the modified map's coverage or had its in-map length
change. Anyone needing the emergent
CARLA-observed effect should look at the measured corridor KPIs, or watch the
live CARLA run itself.

The heatmap is rendered (optional `viz`/matplotlib extra,
`infrastructure.reporting.heatmap`) as a **per-segment congestion
choropleth** -- each real segment's polyline colored by its congestion index
-- not an interpolated spatial-density raster, since MOTION's traffic model
is segment-based, not a spatial density field.

## CO2 approximation

`domain.kpi.DEFAULT_GRAMS_CO2_PER_VEHICLE_KM = 120.0` grams per vehicle-km is
a rough, commonly cited average-passenger-car figure -- not sourced from a
validated fleet-composition or emissions model. No vehicle type, fuel type or
driving-condition adjustment is modeled. It mirrors the simplification
requested for UC-03 ("stima come consumo medio per autovettura") and is
overridable per run via `--grams-co2-per-km`, matching this repository's
existing honesty stance toward approximate research figures (see
[model-card.md](model-card.md) for the same treatment of the legacy
behavioral classifier).

## Limitations summary

- Baseline and scenario KPIs are not independently annotated ground truth;
  they are derived quantities from HERE traffic data and MOTION's own
  simulation/allocation policies.
- Only `SPEED_LIMIT_CHANGE` (UC-02) analytically changes the measured
  corridor KPIs through MOTION's own domain model; every other modification
  kind's effect on those numbers depends on a live CARLA run.
- The UC-03 heatmap's "after" state is a policy prediction, not a
  measurement, and will resemble "before" for most modification kinds by
  construction.
- The CO2 figure is a flat per-vehicle-km approximation, not a validated
  emissions model.
- `TrafficSimulator.average_speed_kmh()` reflects only session-owned,
  currently-live actors at the moment it is read; it is not a time-averaged
  or distance-weighted measurement across the whole tick window.
