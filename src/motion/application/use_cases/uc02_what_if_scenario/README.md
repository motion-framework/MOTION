# UC-02 -- What-If Scenario Editor

Compare a policy or infrastructure change against MOTION's real traffic
baseline, before anything changes in the real world.

**Actor:** governance operator.
**Precondition:** UC-01 is usable for the target area (a HERE-covered road
you can propose a map for).

## What this package does, and does not, do

- It proposes a real road segment from live HERE traffic data, provisions a
  baseline OpenStreetMap/OpenDRIVE map for it (reusing exactly what
  `motion map mirror-road` does), and estimates the current vehicle count
  from the map's field-device positions.
- It hands you a **copy** of that map's `.osm` file and waits for you to
  edit it in an external tool -- **JOSM** (<https://josm.openstreetmap.org/>)
  is the reference tool, but any editor that produces valid OSM XML works.
  MOTION does **not** edit map geometry itself.
- It converts and repairs your edited map into OpenDRIVE (the same
  conversion/repair pipeline UC-01 provisioning uses), then re-runs UC-01's
  own population/speed-mirroring loop (`TrafficMirrorService`) against the
  modified map in CARLA -- **not** the separate CARLA ScenarioRunner
  framework. This is a deliberate substitution: `TrafficMirrorService` is
  proven, already-tested code that does the functional job (drive traffic on
  a map, observe the result); integrating ScenarioRunner's own
  OpenSCENARIO-based execution engine would be a much larger, separately
  scoped effort for the same practical outcome.
- It reports a **measured** KPI delta: the baseline numbers come directly
  from real HERE segment data; the scenario numbers come from what the
  simulator actually observed after running on the modified map
  (`TrafficSimulator.owned_vehicle_count()` and the newly-added
  `average_speed_kmh()`), not from an echo of commanded policy.

See `docs/scenario-kpis.md` at the repository root for the exact KPI
methodology and its documented approximations (in particular: MOTION's own
domain model is bbox/speed-limit-level, not road-topology-level, so a lane or
road closure's effect on the *measured* KPIs depends on how CARLA's own
TrafficManager actually reroutes traffic on the modified map at simulation
time -- not on anything MOTION computes analytically).

## Modification kinds (`--modification-kind`)

| Kind | Meaning | Feeds domain policy? |
|---|---|---|
| `LANE_CLOSURE` | A lane is closed on the edited map. | No -- geometry only; effect is realized by CARLA at simulation time. |
| `ROAD_CLOSURE` | A road/segment is closed on the edited map. | No -- same as above. |
| `SPEED_LIMIT_CHANGE` | The area's speed limit changes. | **Yes** -- pass `--modified-speed-limit-kmh`; it replaces the map's speed limit for the scenario run's `SpeedMirrorPolicy`. |
| `SIGNAL_ADDED` | A traffic signal is added on the edited map. | No. |
| `SIGNAL_REMOVED` | A traffic signal is removed on the edited map. | No. |
| `EVENT_DIVERSION` | Traffic is diverted for an event (concert, demonstration, ...). | No. |
| `INCIDENT_SIMULATION` | An incident and its queue propagation are simulated. | No. |

"Feeds domain policy" means MOTION itself changes a number it computes with
(only the speed limit, today). Every other kind is recorded as descriptive
metadata on the scenario record; its real-world effect only shows up in the
measured KPIs to the extent CARLA's simulation reacts to your edited map.

## Step-by-step usage

All three commands are offline-testable except `apply` (needs the CARLA
Python API for OSM-to-OpenDRIVE conversion) and `simulate` (needs a reachable
CARLA simulator). `stage` needs `HERE_API_KEY` set, like `map mirror-road`.

### 1. Stage

```bash
motion scenario stage \
  --lat 40.6772 --lon 14.7604 --radius 400 --name salerno --geo \
  --modification-kind LANE_CLOSURE \
  --notes "Close the northbound lane on Via X for resurfacing"
```

For a speed-limit scenario, add the numeric override:

```bash
motion scenario stage \
  --lat 40.6772 --lon 14.7604 --radius 400 --name salerno --geo \
  --modification-kind SPEED_LIMIT_CHANGE \
  --modified-speed-limit-kmh 30
```

Expected output:

```
Scenario staged: 20260817-142530-a1b2c3 (UC-02)
Modification: LANE_CLOSURE -- Close the northbound lane on Via X for resurfacing
Edit the staged OSM file with an external tool (e.g. JOSM), save it, then run:
  motion scenario apply 20260817-142530-a1b2c3   (or: infra-event apply)
Editable file: data/maps/salerno__scenario-20260817-142530-a1b2c3/salerno__scenario-20260817-142530-a1b2c3.osm
```

What got written to disk:

- The **baseline** map: `data/maps/salerno/salerno.osm` and
  `salerno_map.xodr` -- exactly as `motion map mirror-road` would produce.
  It also becomes the registered active map
  (`var/runtime/active_map.json`), matching the UC-02 precondition that a
  real UC-01 baseline is available.
- The **editable copy**: `data/maps/salerno__scenario-<id>/salerno__scenario-<id>.osm`
  -- a plain copy of the baseline OSM, not yet converted.
  It is **not** registered as the active map.
- A **scenario record**: `var/runtime/scenarios/<id>.json` -- tracks status,
  the modification, and (later) the KPI report. All of the above are
  git-ignored generated state, matching `data/*`/`var/` project conventions.

### 2. Edit externally

Open the editable file printed above in JOSM (or any OSM editor), make the
change described by your `--modification-kind`, and **save it in place** --
same filename, same location.

### 3. Apply

```bash
motion scenario apply 20260817-142530-a1b2c3
```

This converts your edited OSM into OpenDRIVE and repairs known defects
(zero-length geometry, object overflow), the same way baseline provisioning
does. Requires the CARLA Python API to be importable.

```
Scenario ready: 20260817-142530-a1b2c3
Variant OpenDRIVE: data/maps/salerno__scenario-20260817-142530-a1b2c3/salerno__scenario-20260817-142530-a1b2c3_map.xodr
```

### 4. Simulate

```bash
motion scenario simulate 20260817-142530-a1b2c3 --ticks 3
```

Add `--offline` to drive it from the synthetic HERE-compatible provider
instead of live HERE (useful for testing the pipeline without credentials --
see `motion mirror --offline` for the same idea on UC-01). Add
`--grams-co2-per-km` to override the default CO2 approximation (120 g/km).
Add `--carla-exe` if CARLA needs to be launched rather than already running.

```
============================================================
MOTION UC-02 | SCENARIO 20260817-142530-a1b2c3 DELTA REPORT
Ticks simulated: 3
------------------------------------------------------------
Metric                          Baseline    Scenario   Delta
Travel time (s)                     42.1        51.7    +9.6
Density (veh/km)                    18.40       14.10   -4.30
CO2 (g)                            5820.0      4460.5 -1359.5
============================================================
```

The scenario record's `status` becomes `SIMULATED` and its `kpi_report` field
holds this same data as JSON, at `var/runtime/scenarios/<id>.json`.

## Troubleshooting

- **`apply` fails with "No edit detected"**: the editable OSM file's SHA-256
  still matches what was staged. You need to actually save a change in your
  editor first.
- **`apply`/`simulate` raise a CARLA import error**: install and configure a
  CARLA Python API wheel matching your simulator, as for any other MOTION
  command that touches CARLA.
- **`stage` fails with a HERE error**: set `HERE_API_KEY` in `.env` (same
  requirement as `motion map mirror-road`).
- **Scenario not found**: `apply`/`simulate` take the exact `scenario_id`
  printed by `stage`; it's also the JSON filename under
  `var/runtime/scenarios/`.

## Reused MOTION components (not reimplemented here)

- `application.road_selection` and `application.map_provisioning` -- baseline
  road proposal and map provisioning (identical to `motion map mirror-road`).
- `application.scenario_workflow` -- shared with UC-03: editable-copy
  staging, edited-map conversion/repair, and the frozen-traffic replay used
  for a fair baseline/scenario comparison.
- `application.traffic_providers` -- shared with `motion mirror`: identical
  live/offline HERE selection.
- `uc01_real_time_traffic_mirroring.service.TrafficMirrorService` and
  `infrastructure.carla.adapter.CarlaTrafficSimulator` -- the actual
  modified-map simulation loop.
- `domain.kpi` -- shared with UC-03: the KPI math itself.
