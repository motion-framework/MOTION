# MOTION

*sMart lighting tO improve safeTy and electricIty cOnsumptioN*

MOTION is the shared research-software repository for the project's mobility,
simulation, environmental-analysis and decision-support work. It is organised
around seven Macro Use Cases, with common architecture, interfaces,
documentation and quality gates intended to support their incremental
development.

## Repository status

This initial codebase comes from the re-engineering of a thesis prototype.
**UC-01 is currently the only implemented end-to-end use case.** The
packages for UC-02–UC-07 provide scope and traceability metadata, but they do not
yet expose executable workflows.

The project-wide Python package and installed command are both named `motion`,
matching the MOTION project rather than the scope of a single use case. UC-01
remains explicitly identified by its `uc01_real_time_traffic_mirroring` package.
This is a deliberate breaking namespace migration: no legacy package, console
command or project-root environment-variable alias is exposed.

## Macro Use Cases

| UC | Goal | Status |
|---|---|---|
| UC-01 Real-Time Traffic Mirroring | Synchronise observed traffic with a CARLA traffic twin. | **IMPLEMENTED** |
| UC-02 What-If Scenario Editor | Compare policy/infrastructure changes with a real baseline. | **NOT IMPLEMENTED / RESEARCH DIRECTION** |
| UC-03 Infrastructure Event Simulation | Evaluate traffic/environmental effects of urban changes. | **NOT IMPLEMENTED / RESEARCH DIRECTION** |
| UC-04 Multivariate Traffic Prediction | Forecast network traffic over 15-minute-to-24-hour horizons. | **NOT IMPLEMENTED / RESEARCH DIRECTION** |
| UC-05 Environmental Impact Forecast | Forecast CO2/air-quality risk and intervention effects. | **NOT IMPLEMENTED / RESEARCH DIRECTION** |
| UC-06 Luminosity Anomaly Detection | Detect measured-versus-expected luminosity anomalies. | **NOT IMPLEMENTED / RESEARCH DIRECTION** |
| UC-07 Governance Alerts | Produce auditable decision-support recommendations and delivery. | **NOT IMPLEMENTED / RESEARCH DIRECTION** |

Each UC has a dedicated package under
`motion.application.use_cases`.  Packages for unavailable workflows
contain traceability metadata only and expose no executable command. See
[docs/use-cases.md](docs/use-cases.md) for evidence, dependencies and gaps.

The behavioral Random Forest is **not UC-04, UC-06 or UC-07**.  It predicts the
legacy binary `incident_detected` label for an individual vehicle from
`speed_kmh`, `throttle`, `brake`, `steer` and `weather_rain`; it does not forecast
network traffic, luminosity or governance actions.

## Implemented module: UC-01 — Real-Time Traffic Mirroring

MOTION's implemented UC-01 module turns a selected HERE-covered road into a
validated OSM/OpenDRIVE map, loads that map in CARLA, and synchronises the
population and speed policy of session-owned vehicles with HERE Traffic and
synthetic field-device observations. The repository also preserves the existing
telemetry → enriched dataset → Random Forest → real-time inference experiment as a
separate, versioned pipeline.

### Current capabilities

- HERE road selection; atomic OSM acquisition; OpenDRIVE conversion, inspection
  and narrow repairs; versioned active-map registration;
- HERE flow/incident parsing, optional integrity-verifiable evidence archives
  and device-derived fallback when live traffic is unavailable;
- UC-01 population and speed mirroring, with explicit CARLA lifecycle,
  TrafficManager control, watchdogs and cleanup limited to session-owned actors;
- CARLA telemetry collection and deterministic construction of behavioral
  datasets with a versioned feature contract;
- fixed-contract Random Forest training, verified persistence and per-vehicle
  inference tracking;
- an installed CLI with offline tests, static analysis, packaging and CI.

## MOTION and OR3 context

MOTION describes an integrated platform for monitoring and managing mobility,
environmental and urban services. OR3 (*Metodi e strumenti di analisi
veicolare*) covers research, specification and predictive methods for vehicle,
traffic and behaviour analysis. The seven Macro UCs also span simulation,
environmental monitoring and decision support.

Each Macro UC is tracked individually, and implementation status is based on
executable repository evidence. CARLA, HERE, ScenarioRunner and Traffic4cast
are technical choices or research directions in this repository; their mention
does not imply that every related workflow is implemented.

## Architecture

Domain modules perform no I/O and do not import CARLA, Requests, pandas or
scikit-learn. External adapters implement the ports used by application
services. UC-01 owns application orchestration; reusable HERE, OSM and CARLA
logic remains outside the UC package. The CLI is the composition root and
contains no traffic policy.

More detail, including data-flow diagrams and intentional compatibility rules,
is in [docs/architecture.md](docs/architecture.md).  The original-system analysis
and migration record are in
[docs/software-archaeology.md](docs/software-archaeology.md).

## Repository structure

```text
.
├── Dockerfile                     runtime and offline-test image targets
├── compose.yaml                   MOTION runtime and offline-test workflows
├── constraints.txt                reproducible container/CI resolution
├── pyproject.toml                 package, tools and dependency contracts
├── src/motion/
│   ├── application/              provisioning, selection and UC services
│   ├── config/                   static settings, paths and runtime state
│   ├── domain/                   pure traffic/geospatial/device policies
│   ├── infrastructure/           HERE, OSM, map and CARLA adapters
│   ├── ports/                    external-boundary protocols
│   ├── prediction/               behavioral dataset/model/inference contracts
│   └── cli.py                    installed command and composition root
├── tests/                        characterization, unit and integration tests
├── docs/                         architecture, UCs and regression evidence
├── data/reference/               curated source/reference data with provenance
├── artifacts/reference/          curated legacy model with provenance
└── .github/workflows/ci.yml       native and container quality gates
```

Generated maps, telemetry, models, output and runtime state are ignored by Git.
Curated reference artifacts remain explicitly eligible for version control and
carry provenance or integrity metadata.

## Requirements and installation

Validated project tooling targets **Python 3.12**. Other Python versions are not
claimed as supported. Core package import and offline map/HERE logic require
Requests and pyproj:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --editable .
```

Install only the optional dependency groups required by the commands you intend
to run:

```bash
python -m pip install --editable ".[carla]"
python -m pip install --editable ".[ml]"
python -m pip install --editable ".[dev,ml]"
```

`pyproject.toml` is the package dependency contract; the repository does not
maintain a duplicate `requirements.txt`. In `pip install --editable ".[ml]"`,
`--editable` links the checkout into the environment and `[ml]` selects the
behavioral-analysis extra. For a non-editable installation use
`python -m pip install ".[ml]"`.

CARLA is not a core dependency. The optional `[carla]` extra pins the official
Python client to 0.9.16, matching the external simulator version targeted by
this repository. PyPI provides that release only as Windows and Linux x86-64
wheels. Live interoperability is outside the offline gate and must be checked
against the selected simulator host.

## Configuration

Copy `.env.example` to `.env` and provide only local values.  The main settings
are:

| Variable | Purpose | Default |
|---|---|---|
| `MOTION_PROJECT_ROOT` | Explicit data/config root for an installed wheel outside the source checkout. | detected checkout, then current directory |
| `HERE_API_KEY` | HERE Traffic credential. | empty |
| `HERE_ARCHIVE_MODE` | `off` or raw-response evidence `record`. | `off` |
| `CARLA_HOST`, `CARLA_PORT` | CARLA RPC endpoint. | `localhost`, `2000` |
| `CARLA_TRAFFIC_MANAGER_PORT` | TrafficManager endpoint. | `8000` |
| `CARLA_CLIENT_TIMEOUT_SECONDS` | Readiness/load timeout. | `120` |
| `CARLA_EXECUTABLE_PATH` | Optional simulator executable to launch. | empty |
| `OSM_DOWNLOADER_CONTACT_EMAIL` | Contact metadata for Overpass etiquette. | empty |
| `OSM_OVERPASS_ENDPOINTS` | Ordered comma-separated `/api/map` endpoints. | three public endpoints |
| `MIRROR_UPDATE_INTERVAL_SECONDS` | HERE/device refresh interval. | `60` |
| `MIRROR_ROAD_FILTER` | Optional case-insensitive road-name filter. | empty |
| `MIRROR_GEO_FILTER`, `MIRROR_ANCHOR_FC` | Optional registered-area/functional-class filters. | disabled, empty |

Inside Compose, `CARLA_HOST` defaults to `host.docker.internal`; set it to a
DNS name or IP address when CARLA runs on another machine. The application
default remains `localhost` for native Python execution.

`.env` contains static local configuration and secrets only.  Provisioning
writes generated state atomically to `var/runtime/active_map.json`, including
the active bbox, map paths, device registry and selection filters.  A read-only
compatibility loader accepts former `MAP_*` environment variables but never
rewrites `.env`.

## Docker and Compose

MOTION can run in Docker without a host Python installation. CARLA remains an
external simulator and is never started by Compose.

### Commands that do not require CARLA

Build the default image and run the CLI:

```bash
docker compose build motion
docker compose run --rm --no-deps motion --help
docker compose run --rm --no-deps motion uc-status --json
```

Run the offline suite with:

```bash
docker compose --profile test build motion-test
docker compose --profile test run --rm --no-deps motion-test
```

These images include the core, ML and test dependencies but omit the CARLA
client. They support CLI inspection, map inspection, dataset and model commands,
and all tests that use local fixtures or fake external boundaries.

### Commands that require CARLA

Start CARLA 0.9.16 separately, then build the image containing the matching
Python client:

```bash
docker compose --profile carla-client build motion-carla
docker compose --profile carla-client run --rm --no-deps \
  motion-carla mirror --offline --once
```

The mirror command also requires an active map. On Docker Desktop, Compose uses
`host.docker.internal` when `CARLA_HOST` is unset; set `CARLA_HOST` to a DNS name
or IP address for a remote simulator. The default ports are 2000 for RPC, 2001
for streaming and 8000 for the Traffic Manager.

Compose reads the existing MOTION environment variables and bind-mounts
`data/`, `artifacts/`, `var/` and `outputs/`. Generated files therefore remain
in the checkout after a container is removed. See
[docs/docker.md](docs/docker.md) for map provisioning, configuration, platform
support and troubleshooting.

## Quick start

Inspect implementation status and the installed command surface without CARLA
or credentials:

```bash
motion uc-status
motion --help
motion map --help
```

Provision a named map directly from a centre/radius. This command needs network
access to Overpass and a compatible CARLA Python API for Osm2Odr conversion:

```bash
motion map provision \
  --name salerno \
  --lat 40.6772 --lon 14.7604 --radius 400
```

Road selection additionally requires `HERE_API_KEY`:

```bash
motion map mirror-road \
  --lat 40.6772 --lon 14.7604 --radius 400 --name salerno --geo
```

The full UC-01 flow also requires a reachable CARLA simulator:

```bash
motion mirror \
  --lat 40.6772 --lon 14.7604 --radius 400 --name salerno --geo
```

Reuse the registered active map without another OSM/OpenDRIVE build:

```bash
motion mirror --skip-provision
```

Run one complete UC-01 integration tick without HERE or Overpass, using the
registered active map, synthetic field-device readings and synthetic traffic
payloads that match the HERE v7 subset consumed by this project:

```bash
motion mirror --offline --once
```

Offline mode still requires a reachable CARLA simulator. It does not construct
an HTTP client, provision a map or accept road-selection coordinates. Synthetic
flow payloads use the HERE `results`/`location`/`currentFlow` structure and pass
through the production `HereTrafficProvider`, `TrafficParser` and
`IncidentParser`; their values are artificial and are not evidence of live
traffic conditions.

Use `--once` for one refresh tick and `--check-calibration` or
`--verify-calibration` for opt-in CARLA map checks. Live commands fail if their
configured HERE, Overpass or CARLA boundary is unavailable.

## CLI reference

| Command | Capability |
|---|---|
| `motion uc-status [--json]` | Print UC-01–UC-07 traceability status. |
| `motion map provision` | Download, convert, repair and register an area. |
| `motion map mirror-road` | Select a HERE road and provision its map. |
| `motion map inspect PATH` | Inspect OSM counts and bounds. |
| `motion map validate PATH` | Scan all supported OpenDRIVE defects. |
| `motion map repair PATH` | Apply supported repairs with backups. |
| `motion map scan-degenerate PATH` | Report invalid geometry lengths. |
| `motion map scan-overflow PATH` | Report objects beyond road length. |
| `motion map patch-zero PATH` | Patch exactly zero-length geometries. |
| `motion map patch-overflow PATH` | Clamp overflowing objects. |
| `motion map convert-active` | Reconvert the registered OSM map. |
| `motion mirror` | Execute UC-01; `--offline` runs against the active map without HERE/Overpass. |
| `motion here verify-archive PATH` | Verify archived snapshot hashes. |
| `motion telemetry collect` | Collect CARLA vehicle telemetry. |
| `motion dataset build` | Build one enriched behavioral dataset from explicit CSVs. |
| `motion model train` | Train/evaluate and persist the fixed Random Forest contract. |
| `motion model infer` | Run CARLA behavioral inference and write summary statistics. |
| `motion diagnostics speed-units` | Run the opt-in TrafficManager unit diagnostic. |
| `motion diagnostics calibration` | Check registered map/geographic alignment. |

Run any command with `--help` for its complete option set. The former standalone
scripts were removed after their capabilities were migrated to this CLI.

## Telemetry and behavioral analysis

Collect explicit CARLA sessions, build a dataset, train and infer through
separate commands. Telemetry collection attaches to the current CARLA world;
model inference also requires a registered active map and CARLA:

```bash
motion telemetry collect \
  --duration 180 --interval 0.5 --output data/telemetry

motion dataset build \
  data/telemetry/session-a.csv data/telemetry/session-b.csv \
  --output data/telemetry/behavioral.csv

motion model train \
  --dataset data/telemetry/behavioral.csv \
  --output artifacts/models/traffic_aimodel.pkl

motion model infer \
  --model artifacts/models/traffic_aimodel.pkl \
  --stats-output outputs/realtime_inference_results.txt
```

The dataset builder assigns every input a `session_id`. The feature order and
target are versioned. `weather_rain` must be present or the dataset command must
receive an explicit `--weather-rain-default`; otherwise construction fails.
Labels are shifted within a vehicle/session, and train/test groups are separated
by session. A deterministic row split is
used only when an external or legacy dataset without `session_id` is supplied
directly to `model train`; the training summary records that fallback.

New model artifacts use validated metadata and SHA-256 sidecars plus atomic
file replacement.  Because joblib uses pickle semantics, checksums detect damage
but do not make an untrusted artifact safe.  The original raw model is preserved
only as a curated reference under `artifacts/reference/models` with its exact
feature order and digest.  Detailed semantics are recorded in
[docs/data-contracts.md](docs/data-contracts.md) and the limitations/provenance
of the historical estimator in [docs/model-card.md](docs/model-card.md).

## Testing and quality gates

To run locally the checks used by the native CI job:

```bash
python -m pip install --constraint constraints.txt setuptools wheel
python -m pip install --no-build-isolation --constraint constraints.txt --editable ".[dev,ml]"
python -m pip check
python -m ruff check src tests .github/scripts
python -m ruff format --check src tests .github/scripts
python -m mypy src/motion .github/scripts
python -m pytest --cov=motion --cov-report=term-missing
python -m build --no-isolation
```

The containerized offline test gate is:

```bash
docker compose --profile test build motion-test
docker compose --profile test run --rm --no-deps motion-test
```

Characterization tests lock the legacy numerical outputs. Unit tests exercise
domain and application contracts with fake CARLA objects; integration tests
cover filesystem, data and model persistence without live services. CI runs the
native gate and validates the Compose model, CLI and offline container suite on
Linux amd64 and arm64. The amd64 job also imports the optional CARLA client.
Neither path contacts CARLA, HERE or Overpass. See
[docs/testing.md](docs/testing.md) and the complete [non-regression
matrix](docs/non-regression.md).

## Outputs and artifacts

| Path | Contents | Version-control policy |
|---|---|---|
| `var/runtime/` | Active-map state. | Generated, ignored. |
| `data/maps/` | Provisioned OSM/OpenDRIVE maps. | Generated, ignored. |
| `data/telemetry/` | Raw/enriched CSV sessions. | Generated, ignored. |
| `artifacts/here/` | Optional HERE evidence archives. | Generated, ignored; provider terms apply. |
| `artifacts/models/` | Model files with metadata/checksum sidecars. | Generated, ignored. |
| `outputs/` | Inference summaries and reports. | Generated, ignored. |
| `data/reference/` | Curated map inputs with provenance. | Tracked intentionally. |
| `artifacts/reference/models/` | Pinned legacy model and machine-readable provenance. | Tracked intentionally. |

OpenStreetMap attribution and third-party data constraints are documented in
[NOTICE.md](NOTICE.md).  HERE response use remains subject to the applicable
account and service terms.

## Limitations and research status

- The end-to-end CARLA, HERE and Overpass workflows require their real external
  environments and were not executed by the offline quality gate.
- The field-device provider is synthetic; no production device connector or
  governance dashboard is present.
- UC-02–UC-07 are documented research directions and have no implementation.
- UC-05 ownership/method and several UC-07 delivery semantics remain unresolved.
- Session-free legacy datasets retain a row-level split for compatibility; their
  evaluation is more leakage-prone and is labeled accordingly.
- Independent segment rounding can exceed the nominal total by one; this
  baseline behavior is frozen by characterization tests.
- The official CARLA 0.9.16 client wheel is x86-64; the default MOTION and test
  images omit that client and also build on Linux arm64.
- Compose does not start CARLA. Live simulator interoperability was not part of
  the ordinary CI gate.

## External resources 

- [CARLA simulator](https://carla.org/)
- [HERE Traffic API](https://docs.here.com/traffic-api/docs/introduction-to-here-traffic-api-v7)
- [OpenStreetMap](https://www.openstreetmap.org/copyright) and
  [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)
