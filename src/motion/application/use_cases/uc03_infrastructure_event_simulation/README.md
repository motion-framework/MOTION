# UC-03 -- Infrastructure Event Simulation

Evaluate the traffic and environmental effect of a proposed urban
infrastructure change -- a new parking area, an extended limited-traffic
zone (ZTL), or a roundabout replacing a signal -- against MOTION's real
traffic baseline.

**Actor:** urban planner / governance.
**Precondition:** same as UC-02 -- a HERE-covered area you can propose a map
for.

## What this package does, and does not, do

UC-03 shares its entire pipeline with UC-02 (`stage` -> external edit ->
`apply` -> `simulate`, via the shared `application.scenario_workflow`
module) -- see
[`uc02_what_if_scenario/README.md`](../uc02_what_if_scenario/README.md) for
the parts that are identical (baseline provisioning, external editing,
conversion/repair, why UC-01's own mirroring loop is reused instead of CARLA
ScenarioRunner). This document only covers what's different.

UC-03's `simulate` step additionally produces:

- A **congestion heatmap**: a before/after image (`.png`, via the optional
  `viz`/matplotlib extra) showing each real corridor segment colored by
  congestion. **"Before"** is the real HERE `jam_factor` for that segment.
  **"After"** is MOTION's own population-allocation policy
  (`domain.population.segment_target_vehicle_count` -- the per-segment half of
  what UC-01's mirroring loop uses to populate CARLA) evaluated against the
  modified map. **This is a policy prediction, not a per-vehicle CARLA
  measurement.** MOTION's domain model tracks a bounding box and a speed
  limit, not lane counts or road topology, so for most of UC-03's
  modification kinds (all except a hypothetical future speed-limit-like
  parameter) the heatmap's "after" state will closely track "before" unless
  you inspect the live CARLA run yourself -- an emergent effect of
  TrafficManager's own pathfinding on your edited OpenDRIVE map that MOTION's
  analytical KPIs do not, and cannot, capture without per-vehicle telemetry.
  This is stated plainly so the heatmap is never mistaken for more than it
  is. Both panels share one scale: "after" converts the allocated vehicles
  back to a jam factor with the same density formula the allocation uses, so
  an unchanged allocation reproduces the "before" colour exactly instead of
  implying relief the scenario did not cause.
- A corridor-level KPI delta (average travel time, density) and an area CO2
  estimate -- computed exactly like UC-02's, from the same measured
  post-simulation `TrafficSimulator.average_speed_kmh()` /
  `owned_vehicle_count()`.

## Modification kinds (`--modification-kind`)

| Kind | Meaning |
|---|---|
| `NEW_PARKING` | A new parking area/access is added on the edited map. |
| `ZTL_EXTENDED` | The limited-traffic zone (ZTL) is extended on the edited map. |
| `ROUNDABOUT_VS_SIGNAL` | A roundabout replaces a signal (or vice versa) on the edited map. |

None of these currently feed a numeric domain parameter (unlike UC-02's
`SPEED_LIMIT_CHANGE`); MOTION has no lane/parking/junction-type model to
change a number with. They are recorded as descriptive metadata only.

## Step-by-step usage

`stage` needs `HERE_API_KEY`; `apply` needs the CARLA Python API; `simulate`
needs a reachable CARLA simulator **and** the `viz` extra installed
(`pip install --editable ".[viz]"`) for heatmap rendering.

### 1. Stage

```bash
motion infra-event stage \
  --lat 40.6772 --lon 14.7604 --radius 400 --name salerno --geo \
  --modification-kind ZTL_EXTENDED \
  --notes "Extend the ZTL to cover Piazza Y"
```

Output and generated files are identical in shape to UC-02's `stage` (see
that package's README) -- baseline map + registered active map, editable OSM
copy, and a `ScenarioRecord` at `var/runtime/scenarios/<id>.json`, this time
with `use_case_id: "UC-03"`.

### 2. Edit externally

Same as UC-02: open the editable OSM file in JOSM (or any OSM editor), make
the change, save in place.

### 3. Apply

```bash
motion infra-event apply <scenario-id>
```

Identical mechanics to UC-02's `apply`.

### 4. Simulate

```bash
motion infra-event simulate <scenario-id> --ticks 3 \
  --heatmap-output outputs/scenarios/my_ztl_scenario.png
```

`--heatmap-output` is optional; it defaults to
`outputs/scenarios/<scenario-id>_heatmap.png` (git-ignored, like every other
generated output under `outputs/`). `--ticks`, `--settle-seconds` (default 20),
`--offline`, `--grams-co2-per-km` and `--carla-exe` behave exactly as in
UC-02.

```
============================================================
MOTION UC-03 | SCENARIO 20260817-143012-d4e5f6 REPORT
Ticks simulated: 3
------------------------------------------------------------
Corridor travel time : 4029.8s -> 9696.7s (+5666.8s)
Corridor density     : 3.58 -> 2.85 veh/km (-0.74)
Area CO2 estimate    : 203666g -> 161889g (-41778g)
Congestion heatmap   : 49 segment(s), image at outputs/scenarios/20260817-143012-d4e5f6_heatmap.png
============================================================
```

## Troubleshooting

- Everything in UC-02's troubleshooting section applies here too.
- **`simulate` fails with a matplotlib/heatmap-rendering error**: install the
  `viz` extra: `pip install --editable ".[viz]"`. Without it, `stage` and
  `apply` still work; only heatmap rendering in `simulate` needs matplotlib.
- **The heatmap looks identical before/after**: expected for most
  modification kinds, for the reason explained above -- MOTION's allocation
  depends on the jam factor and the segment's in-map length, neither of which
  a parking, ZTL or junction-type edit changes. Check the live CARLA run
  itself (or the measured corridor travel-time/density delta, which does
  reflect what the simulator actually observed) rather than the heatmap
  alone. A segment that *does* change colour left the modified map's coverage
  or had its in-map length change.

## Reused MOTION components (not reimplemented here)

Same list as UC-02's README, plus:

- `domain.heatmap.build_congestion_heatmap` -- the heatmap cell assembly.
- `infrastructure.reporting.heatmap.render_congestion_heatmap` -- the image
  rendering (lazy matplotlib import; core package import never requires it).
