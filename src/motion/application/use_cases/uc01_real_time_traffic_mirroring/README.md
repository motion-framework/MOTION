# UC-01 -- Real-Time Traffic Mirroring

Keep a CARLA traffic twin of a real road in step with observed traffic:
vehicle population and driving speed follow live HERE Traffic data (and
field-device readings), refreshed on a fixed interval.

**Actor:** automatic system.
**Precondition:** a HERE-covered road (or an already provisioned active map)
and a reachable CARLA simulator.

UC-01 is also the baseline UC-02 and UC-03 compare against: both reuse this
package's `TrafficMirrorService` to drive their modified maps.

## What this package does, and does not, do

- It selects a real road from live HERE flow data -- interactively, or
  automatically with `--geo` -- cuts a map area around it, places field-device
  anchors along that road, and provisions a validated OpenStreetMap/OpenDRIVE
  map for it (download, Osm2Odr conversion, narrow geometry repairs). The map
  is then registered as the **active map** (`var/runtime/active_map.json`).
- It loads that OpenDRIVE map into CARLA and, on every tick:
  1. polls the field devices and fetches HERE flow/incident segments;
  2. keeps only the segments relevant to the mapped road (see *Segment
     filtering* below) and clips them to the map's bounding box;
  3. sets a **per-segment vehicle population** from each segment's HERE jam
     factor and in-map length (`domain.population.derive_population_targets`,
     capped at 80 session-owned vehicles in total);
  4. commands each vehicle through TrafficManager with a **speed policy**
     derived from that segment's observed vs. free-flow speed
     (`domain.mirroring.SpeedMirrorPolicy`): slowdown percentage, target
     speed, longer following distance near incidents, and vehicles held at
     zero speed on closed roads;
  5. re-pins vehicles to the mirrored road path and removes vehicles that
     fell through the map, left the mirrored coverage, or froze in traffic;
  6. prints a console dashboard for the tick. Each segment is labelled
     `FREE` (jam factor < 3), `SLOW` (< 7) or `JAM`.
- Between ticks a watchdog keeps removing tilted/off-road or fallen vehicles
  every second until the next refresh (`MIRROR_UPDATE_INTERVAL_SECONDS`,
  default 60 s).
- If HERE acquisition fails mid-run, it does **not** stop: it logs the
  failure (exception type names only -- never URLs, keys or payloads) and
  falls back to a uniform population derived from the field-device counts
  (20-80 vehicles), with a fallback 20 % slowdown.
- It only ever creates, commands and destroys vehicles **it spawned in this
  session**. Other actors in the CARLA world are never touched, and all owned
  vehicles are destroyed on exit (including Ctrl+C).

What it does **not** do:

- **Field devices are synthetic.** `SyntheticDeviceProvider` generates
  plausible count/speed readings at the registered device positions; there is
  no adapter for a real production field-device feed yet.
- **No governance dashboard.** The per-tick report is a console printout,
  not the web dashboard the use-case description refers to.
- It mirrors **population and speed**, not individual vehicles: HERE gives
  aggregate segment flow, so CARLA vehicles are not one-to-one copies of real
  cars.

## Segment filtering

Which HERE segments drive the simulation depends on how the map was made:

| Map source | Filter applied | Effect |
|---|---|---|
| `motion map mirror-road` / `motion mirror --lat ... --lon ...` | Geo filter (set automatically) | Keeps segments with a vertex within 150 m of a field-device anchor, and within +/-1 HERE functional class of the selected road, so cross streets of a different class don't dilute the mirror. |
| `motion map provision` (plain area, no road) | None by default | Every HERE segment touching the map's bounding box is used. Device anchors are synthesized (`GEN_001`..`GEN_004`) along the bbox diagonal. |
| Either, with `MIRROR_ROAD_FILTER=<text>` | Road-name filter | Keeps segments whose HERE description contains the text (case-insensitive). |

Every filter falls back to the unfiltered list rather than to "no traffic"
when nothing matches. `MIRROR_GEO_FILTER` and `MIRROR_ANCHOR_FC` in `.env`
can force the geo filter on for any map.

## Step-by-step usage

`motion mirror` needs `HERE_API_KEY`, network access to Overpass (only when it
provisions a new map), the CARLA Python API, and a reachable CARLA simulator.
`--offline` removes the HERE/Overpass requirement but **still needs CARLA**.

### 1. Provision a map (optional as a separate step)

`motion mirror --lat ... --lon ...` provisions automatically, so this step is
only needed if you want to build the map first and mirror later:

```bash
motion map mirror-road \
  --lat 40.6772 --lon 14.7604 --radius 400 --name salerno --geo
```

Without `--geo` you get an interactive menu of the HERE roads found near the
point (name, segment count, average speed, jam factor) and pick one by number.
`--radius` defaults to 1500 m. Expected output:

```
Active map: salerno
OSM:        data/maps/salerno/salerno.osm
OpenDRIVE:  data/maps/salerno/salerno_map.xodr
Geometry:   0 zero-length repair(s), 2 object clamp(s)
```

What got written to disk (all git-ignored generated state):

- `data/maps/salerno/salerno.osm` -- the OSM extract. It is reused instead of
  downloaded again if it already covers the requested area.
- `data/maps/salerno/salerno_map.xodr` -- the converted and repaired
  OpenDRIVE map.
- `var/runtime/active_map.json` -- the active-map record: bbox, map paths,
  the four device anchors (`SALERNO_001`..`SALERNO_004`, placed along the
  selected road), and the geo/functional-class filter settings. It is written
  only after every build step has succeeded.

### 2. Run the mirror

Provision and mirror in one command:

```bash
motion mirror \
  --lat 40.6772 --lon 14.7604 --radius 400 --name salerno --geo
```

Or reuse the active map from step 1 without rebuilding it:

```bash
motion mirror --skip-provision
```

The service runs until you press Ctrl+C, refreshing every
`MIRROR_UPDATE_INTERVAL_SECONDS`. After each tick it prints a dashboard like
this one (values are illustrative):

```
============================================================
MOTION UC-01 | SALERNO DIGITAL TWIN
Timestamp      : 2026-11-18 10:42:07
Active vehicles: 34  |  Population target: 36
------------------------------------------------------------
FIELD DEVICES:
  SALERNO_001  (40.6768, 14.7581)  count=  9  speed= 27.4 km/h
  SALERNO_002  (40.6771, 14.7598)  count= 12  speed= 33.1 km/h
  ...

HERE FLOW ENRICHMENT:
  Segments  : 3
  Avg speed : 28.6 km/h
  Avg jam   : 3.40 / 10.0
  Via Roma                            speed= 24.0 km/h  jam=4.2  incidents=0  closed=False  [SLOW]
  ...
============================================================
```

### 3. Useful options

| Option | Effect |
|---|---|
| `--once` | Run one tick and exit (cleans up its vehicles). Good for a quick end-to-end check. |
| `--offline` | No HERE or Overpass access. Reuses the active map and drives it from synthetic traffic in the HERE v7 payload shape, passed through the production HERE parsers. Cannot be combined with `--lat/--lon/--radius/--geo`. The dashboard header reads `SYNTHETIC HERE-COMPATIBLE FLOW ENRICHMENT`. |
| `--check-calibration` | Before mirroring, project each device anchor and HERE shape point into CARLA and check it lands within 8 m of a road. Exits with code 1 if any point fails. |
| `--verify-calibration` | Same check, and also draws the points as labelled markers in the CARLA viewport (red = devices, blue = HERE segments). |
| `--carla-exe PATH` | Launch this CARLA executable if no server is already running (overrides `CARLA_EXECUTABLE_PATH`). |

The quickest check that does not need HERE credentials:

```bash
motion mirror --offline --once
```

Synthetic values are artificial: they exercise the pipeline, not real traffic
conditions.

## Troubleshooting

- **`--lat and --lon are required unless --skip-provision is used`**: either
  give coordinates to provision a new map, or pass `--skip-provision` /
  `--offline` to reuse the active map.
- **`No active map state. Provision a map first ...`**: run step 1 (or
  `motion map provision`) first; `--skip-provision` and `--offline` never
  create a map.
- **`HERE returned no traffic segments for the requested area`**: HERE has
  no flow data around that point; increase `--radius` or move the point onto
  a main road.
- **HERE errors at startup**: set `HERE_API_KEY` in `.env`. Once the
  mirror is running, HERE outages only produce a warning and the
  device-derived fallback.
- **CARLA import or connection errors**: install a CARLA Python API wheel
  matching your simulator and check `CARLA_HOST`/`CARLA_PORT`/
  `CARLA_TRAFFIC_MANAGER_PORT`, or pass `--carla-exe` to launch it.
- **Vehicles appear off the road or in the wrong place**: run with
  `--verify-calibration` and look at where the markers land; `motion map
  validate` / `motion map repair` handle the supported OpenDRIVE defects.
- **Very few vehicles**: expected when HERE reports free-flowing traffic --
  population scales with the jam factor (0 at jam 0, up to 120 veh/km at
  jam 10), not with a fixed fleet size.

## Package contents

- `service.py` -- `TrafficMirrorService`: `prepare`, `run_tick`,
  `watch_until`, `run_forever`, `close`. It depends only on ports
  (`TrafficDataProvider`, `FieldDeviceProvider`, `TrafficSimulator`), so it is
  tested with fakes and reused by UC-02/UC-03.
- `coverage.py` -- `MapCoverage`: clips HERE segment geometry to the map bbox
  and projects it to CARLA x/y.
- `filtering.py` -- `SegmentFilter`: the road-name and geo/functional-class
  filters described above.
- `reporting.py` -- `TickResult`, `ConsoleDashboardReporter`,
  `NullTickReporter`.

The CLI composition (concrete adapters wired into the service) is
`_run_uc01` in `motion/cli.py`.

## MOTION components used (not implemented in this package)

- `application.road_selection` and `application.map_provisioning` -- road
  choice, device placement and map provisioning.
- `application.traffic_providers` -- live HERE vs. offline synthetic provider
  selection (shared with UC-02/UC-03).
- `domain.mirroring`, `domain.population`, `domain.devices` -- the pure speed,
  population and device policies.
- `infrastructure.here` -- HERE flow/incident client and parsers;
  `infrastructure.offline` -- the synthetic HERE-compatible payloads.
- `infrastructure.carla` -- `CarlaTrafficSimulator` (server lifecycle, world
  loading, TrafficManager commands, owned-vehicle registry, sanitizer rules)
  and the calibration check.

Tests: `tests/unit/application/test_uc01_service.py` plus the domain,
road-selection, provisioning and CARLA-boundary suites under `tests/unit/`.
