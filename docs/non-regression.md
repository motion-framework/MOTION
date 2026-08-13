# Behavioral baseline and non-regression matrix

## Baseline method

The baseline was established from source inspection, Git history, deterministic
execution of pure functions, committed artifacts and sanitised boundary
fixtures. Tests under `tests/characterization` encode documented legacy results,
including the independent-rounding anomaly.

Behavior that requires a live CARLA 0.9.x process, HERE credentials or network
access is represented by offline fixtures, ports and fakes. The current suite
contains no live external-system tests.

## Matrix

| Existing capability | Baseline | Final implementation | Verification | Result |
|---|---|---|---|---|
| Bounding box from center/radius | Legacy local metres-per-degree formula and exact HERE/Overpass order. | `domain.geography.BoundingBox` | Characterization and unit tests with exact Salerno values. | Preserved. |
| Geographic/polyline calculations | Local planar approximations and nearest-vertex slicing. | `domain.geography` | Characterization tests. | Preserved. |
| HERE flow parsing | Segment identity, speed, jam factor, confidence, FC, closure and shape extraction. | `infrastructure.here.parser` | Sanitised fixture and malformed-payload tests. | Preserved with validation. |
| HERE incident enrichment | Incidents associated with nearby segments; closure affects behavior. | `infrastructure.here.provider` | Mocked adapter tests. | Preserved. |
| HERE archival | Optional timestamped raw evidence. | Atomic snapshots, manifest and SHA-256 verification in `infrastructure.here.archive`. | Offline persistence/integrity tests. | Preserved with atomic writes and digest verification. |
| HERE failure fallback | Flow failure does not stop the simulator; device state is used. | UC-01 application service logs the cause and uses uniform population. | UC service fake-provider tests. | Preserved; failure type is logged. |
| Synthetic device feed | Timestamped per-device count/speed based on registered coordinates. | `domain.devices.SyntheticDeviceProvider` | Deterministic provider tests/fakes. | Preserved. |
| Explicit offline UC-01 mode | Reuse the active map and exercise CARLA without constructing an HTTP client or contacting HERE/Overpass. | `traffic-mirror mirror --offline`; synthetic HERE v7 DTOs pass through the production HERE provider/parsers, alongside the synthetic device feed. | Payload-contract, parser-path, CLI composition and UC service tests. | Added as an opt-in verification path; values remain artificial. |
| HERE road grouping and automatic ranking | Coverage/confidence/non-motorway ranking and representative geometry. | `application.road_selection` | Characterization tests. | Preserved. |
| Interactive road selection | Displayed `1..N` menu. Legacy Python indexing also accepted 0/negative values. | Validates the documented `1..N` range. | Boundary tests. | Intentionally corrected. |
| Road cut and device placement | Midpoint cut and four deterministic device coordinates. | `application.road_selection` | Exact characterization examples. | Preserved. |
| OSM acquisition | Bbox download with endpoint fallback and local reuse when coverage is sufficient. | `infrastructure.osm.downloader`, provisioning service. | Fake downloader and OSM fixture tests. | Preserved and made atomic. |
| OSM inspection | Counts and explicit/derived bounds. | `infrastructure.maps.osm_inspection` | Minimal OSM fixture. | Preserved. |
| Osm2Odr conversion | CARLA conversion with configured map profile. | `infrastructure.maps.converter` | Boundary tests; real converter requires CARLA. | Code path preserved; external execution unverified here. |
| OpenDRIVE defect scans | Degenerate geometry and object-overflow reporting. | `infrastructure.maps.geometry` | Defective XODR fixture and CLI exit-code tests. | Preserved. |
| OpenDRIVE repairs | Zero-length geometry patch and object `s` clamp with backups. | `infrastructure.maps.geometry` | Fixture round-trip tests. | Preserved. |
| Map registration | Active bbox, paths, device registry and filters survive later commands. | Atomic schema-v1 `var/runtime/active_map.json`; read-only legacy-env fallback. | Config/state tests including invalid schema. | Preserved with schema validation and atomic writes. |
| CARLA startup/connect/map load | Optional executable launch, readiness wait, OpenDRIVE world load and TrafficManager setup. | `infrastructure.carla.lifecycle` | Fake-CARLA boundary tests. | Preserved; live environment unverified. |
| CARLA client/load timeout | Readiness checks allowed 120 seconds, but the mirror recreated a client with a conflicting 15-second timeout before expensive world generation. | One validated `CARLA_CLIENT_TIMEOUT_SECONDS` setting, default 120, owns the lifecycle boundary. | Settings and fake-lifecycle tests. | Intentionally corrected. |
| Population from segment congestion | Jam-factor density, closure=max density, independent scaling/rounding. | `domain.population` and CARLA population adapter. | Characterization includes nominal max 80 yielding 81. | Preserved, ambiguity documented. |
| Device-only population fallback | Count mapping constrained to 20–80 vehicles. | `domain.mirroring.derive_target_vehicle_count` | Exact empty/3/15/100 baselines. | Preserved. |
| Vehicle spawning/culling | Hysteresis, 40-spawn tick budget, lane projection and coverage filtering. | `infrastructure.carla.population` | Fake-world boundary tests. | Preserved with owned-actor constraint. |
| Vehicle cleanup | Legacy implementation could destroy every world vehicle. | Explicit registry destroys only session-owned actors. | Regression test with foreign actor. | Intentionally corrected for safety. |
| HERE-to-TrafficManager speed | Exact free-flow/closure/fallback command policy. | `domain.mirroring.SpeedMirrorPolicy` | Exact command characterization tests. | Preserved. |
| Road pinning and sanitization | Re-pin, out-of-coverage, fallen/frozen/tilted cleanup and watchdog. | CARLA commander/sanitizer adapters. | Fake actor/world tests. | Preserved. |
| 60-second refresh | HERE/device refresh each minute with between-tick watchdog. | Configurable UC-01 interval, default 60 seconds. | Service clock/sleep tests. | Preserved. |
| Telemetry collection | Vehicle kinematics/control/collision CSV. | CARLA telemetry adapter with declared schema including weather. | Offline schema tests; live CARLA unverified. | Preserved and made pipeline-compatible. |
| Dataset enrichment | Stuck/jam/collision/deceleration labels. | `prediction.enrichment` with explicit CSV inputs. | Unit/integration dataset tests. | Preserved; cross-vehicle label leak corrected. |
| Feature order | `speed_kmh`, `throttle`, `brake`, `steer`, `weather_rain`. | Versioned `prediction.schema`. | Schema, training and artifact tests. | Preserved. |
| Missing rain behavior | Collector omitted required feature, causing pipeline failure. | Collector supplies rain; builder requires it or an explicit default. | Missing/default tests. | Intentionally corrected. |
| Random Forest training | 100 trees, max depth 15, min leaf 5, seed 42, binary target. | `prediction.training` fixed contract. | Deterministic training and metrics tests. | Preserved. |
| Train/test split | Random row split despite README session claim. | Group split when sessions exist; legacy deterministic row fallback otherwise. | Leakage and fallback tests. | Intentionally corrected when evidence permits. |
| Model serialization | Root-level raw joblib model. | Curated legacy artifact retained; new artifacts use separate versioned metadata/checksum sidecars and atomic replacement. | Model persistence/integrity tests. | Preserved with safer new format. |
| Real-time inference | Per-vehicle prediction, confirmation timeout and summary output. | Validated predictor/tracker plus CARLA monitor boundary. | Pure inference/tracker tests; live CARLA unverified. | Preserved. |
| Pending-alert expiry after vehicle disappearance | Legacy expiry depended on receiving another sample for the same vehicle, so state could remain stale indefinitely. | Every tracker sample is also a heartbeat that expires all overdue pending alerts. | Pure tracker transition tests. | Intentionally corrected. |
| Diagnostics/calibration | Speed-unit and geographic calibration scripts. | `traffic-mirror diagnostics` subcommands. | Parser/help tests; live CARLA unverified. | Preserved through the CLI. |
| Root script workflows | Users invoked named Python scripts. | Their capabilities are available as installed `traffic-mirror` subcommands; checkout-only wrappers were removed in the final cleanup. | CLI parser and smoke tests. | Migrated; old filenames retired. |

## Explicit corrections

Seven behaviors were changed intentionally and have focused tests:

1. reject zero/negative interactive road numbers;
2. destroy only actors owned by the current UC-01 session;
3. use the single configured 120-second CARLA boundary timeout instead of the
   conflicting 15-second mirror client timeout;
4. compute future labels within a vehicle/session instead of across vehicles;
5. split by session when that identifier is available;
6. make rain handling an explicit data contract; and
7. expire overdue pending alerts even after their vehicle disappears.

The independent population rounding anomaly and closure-to-maximum-density rule
remain unchanged because the available sources do not justify different
semantics.
