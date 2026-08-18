# Docker execution

MOTION runs in Docker; CARLA 0.9.16 remains a separate simulator process.
Compose does not start or manage CARLA.

## Prerequisites

- Docker Engine or Docker Desktop;
- Docker Compose 2.24 or newer;
- CARLA 0.9.16 only for simulator-dependent commands.

Python and the MOTION dependencies do not need to be installed on the host.

## Common commands

| Task | Command | Requires CARLA |
|---|---|---|
| Show CLI help | `docker compose run --rm --no-deps motion --help` | No |
| Show UC status | `docker compose run --rm --no-deps motion uc-status --json` | No |
| Inspect an OSM file | `docker compose run --rm --no-deps motion map inspect PATH` | No |
| Run the offline test suite | `docker compose --profile test run --rm --no-deps motion-test` | No |
| Run one offline UC-01 tick with an active map | `docker compose --profile carla-client run --rm --no-deps motion-carla mirror --offline --once` | Yes |

Build the default image before the first command:

```bash
docker compose build motion
```

The `motion` image includes the core and ML dependencies. It supports CLI
inspection, map inspection, dataset preparation, model training and the other
commands that do not import the CARLA client.

## Offline tests

Build and run the test image with:

```bash
docker compose --profile test build motion-test
docker compose --profile test run --rm --no-deps motion-test
```

`motion-test` has no network interface. The suite uses fake CARLA objects,
sanitised HERE payloads, local map fixtures and generated tabular data. It does
not contact CARLA, HERE or Overpass.

## Using an external CARLA simulator

Start CARLA 0.9.16 outside Docker, then build the MOTION image containing the
matching Python client:

```bash
docker compose --profile carla-client build motion-carla
```

For CARLA running on the Docker Desktop host, leave `CARLA_HOST` unset. Compose
uses `host.docker.internal`; native Python execution continues to default to
`localhost`.

For CARLA running on another machine, set its DNS name or IP address in `.env`:

```dotenv
CARLA_HOST=simulator.example.net
CARLA_PORT=2000
CARLA_TRAFFIC_MANAGER_PORT=8000
```

Before running `mirror`, start the simulator and register an active map. To
download an area from Overpass, convert it to OpenDRIVE and write the required
`var/runtime/active_map.json` state, run:

```bash
docker compose --profile carla-client run --rm --no-deps \
  motion-carla map provision \
  --name salerno --lat 40.6772 --lon 14.7604 --radius 400
```

Provisioning needs Internet access but does not need a running CARLA server.
The [README quick start](../README.md#quick-start) documents the corresponding
native commands and the HERE-assisted road-selection flow.

Run a single UC-01 tick without HERE or Overpass access:

```bash
docker compose --profile carla-client run --rm --no-deps \
  motion-carla mirror --offline --once
```

Remove `--once` to keep the mirroring loop running. `--offline` disables HERE
and Overpass acquisition; it does not remove the CARLA requirement.

MOTION connects to CARLA through the configured RPC port. With the default
CARLA configuration, TCP 2000 and the negotiated streaming port 2001 must be
reachable from the container. Live mirroring and CARLA diagnostics also create
or connect to a Traffic Manager on `CARLA_TRAFFIC_MANAGER_PORT`, which defaults
to 8000. A single `motion-carla` process owns that Traffic Manager locally;
additional CARLA clients sharing it must be able to reach the same port.

The adapter polls `get_server_version()` while CARLA starts. No fixed startup
delay or Compose healthcheck is used because the simulator is external.

## Configuration

Compose uses the existing MOTION settings. A local `.env` is optional, excluded
from the build context and must not be committed. Compose passes its values to
the container; native execution reads the same file directly.

The container runtime sets:

- `MOTION_PROJECT_ROOT=/workspace`;
- `CARLA_EXECUTABLE_PATH` to an empty value, because Docker does not start the
  simulator;
- `CARLA_HOST=host.docker.internal` when no explicit host is configured.

HERE credentials, timeouts, archive settings and traffic filters retain the
same meaning as in native execution. No `.env` file or credential is copied
into an image.

## Persistent files

Compose bind-mounts the directories where MOTION writes generated data:

| Host | Container | Contents |
|---|---|---|
| `data/` | `/workspace/data` | maps, telemetry and reference data |
| `artifacts/` | `/workspace/artifacts` | HERE archives, models and references |
| `var/` | `/workspace/var` | active-map state |
| `outputs/` | `/workspace/outputs` | inference and experiment outputs |

Removing a container does not remove these files. The CARLA process does not
need access to the mounted directories: MOTION reads the OpenDRIVE file and
sends its content through the CARLA API.

## Images and platforms

Compose defines three MOTION services:

| Service | Purpose | Platform |
|---|---|---|
| `motion` | Runtime with core and ML dependencies | Linux amd64 and arm64 |
| `motion-test` | Offline test environment | Linux amd64 and arm64 |
| `motion-carla` | Runtime with the CARLA 0.9.16 Python client | Linux amd64 |

The CARLA 0.9.16 package has no Linux arm64 wheel, so only `motion-carla` is
fixed to `linux/amd64`. The simulator remains outside every image.

Images run as the unprivileged `motion` user with UID and GID 1000. On Linux,
repositories owned by another UID/GID can be matched at build time:

```bash
MOTION_UID=$(id -u) MOTION_GID=$(id -g) docker compose build motion
```

`pyproject.toml` declares the project dependencies. `constraints.txt` pins the
resolution used by CI and the container builds.

## CI

CI runs the native quality gate first. Container jobs then validate Compose,
build `motion`, smoke-test the CLI and run the offline suite on Linux amd64 and
arm64. The amd64 job also builds `motion-carla` and imports the CARLA client.

CI does not start CARLA and requires no GPU, HERE credential or live external
service.

## Troubleshooting

- **`No active map state`**: provision or register a map before running
  `mirror --offline`.
- **`No module named carla`**: use `motion-carla`, not the default `motion`
  service, for simulator-dependent commands.
- **CARLA connection timeout**: check that CARLA 0.9.16 is running, that the
  configured host is reachable and that ports 2000/2001 and the configured
  Traffic Manager port (8000 by default) are not blocked.
- **Linux bind-mount permission error**: rebuild with `MOTION_UID` and
  `MOTION_GID` matching the repository owner.

## References

- [CARLA 0.9.16 downloads](https://carla.readthedocs.io/en/0.9.16/download/)
- [CARLA Python client 0.9.16 files](https://pypi.org/project/carla/0.9.16/)
- [CARLA client/server connection](https://carla.readthedocs.io/en/0.9.16/tuto_G_getting_started/)
- [Docker Compose environment files](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)
