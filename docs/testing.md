# Testing and validation

## Offline developer gate

```bash
python -m pip install --constraint constraints.txt setuptools wheel
python -m pip install --no-build-isolation --constraint constraints.txt --editable ".[dev,ml]"
python -m pip check
python -m ruff check src tests .github/scripts
python -m ruff format --check src tests .github/scripts
python -m mypy src/motion .github/scripts
python -m pytest --cov=motion
python -m build --no-isolation
```

The constraints file freezes the dependency resolution used by CI and the
container images; `pyproject.toml` remains the package dependency contract.
Native users may omit the constraint when testing the supported dependency
ranges rather than reproducing the gate environment.

The ordinary suite is deterministic and does not need credentials, network
access or a running simulator.  Sanitised HERE JSON, small OSM/OpenDRIVE files,
fake CARLA actors/worlds and generated tabular samples cover external contracts.

## Test layers

- `tests/characterization`: frozen numerical and behavioral outputs from the
  original implementation, including documented anomalies.
- `tests/unit`: pure policies, schemas, application services and boundary
  behavior with fakes.
- `tests/integration`: filesystem/model/data flows that remain offline.

GitHub Actions runs the native gate on Python 3.12.13. After it passes, native
Linux amd64 and arm64 runners validate the Compose model, build `motion`,
smoke-test the CLI and run the suite in `motion-test` with networking disabled.
The amd64 runner also builds `motion-carla` and verifies that the CARLA client
can be imported. Compose does not define or start a simulator service.

The native job retains the JUnit and coverage XML reports, wheel and source
distribution as workflow artifacts for 14 days. These artifacts are diagnostic
and are not published as a MOTION release. The workflow summary shows aggregate
test results, test categories, coverage and the generated distribution files.

Run the container gate locally with:

```bash
docker compose --profile test build motion-test
docker compose --profile test run --rm --no-deps motion-test
```

The suite does not test live CARLA, HERE or Overpass interoperability. Live
CARLA validation requires a separately managed simulator endpoint and is outside
normal CI.

## Coverage interpretation

Coverage uses branch tracking and a configured minimum of 68%. It measures the
offline suite only and is not evidence of live interoperability with CARLA,
HERE or Overpass.
