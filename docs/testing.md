# Testing and validation

## Offline developer gate

```bash
python -m pip install --editable ".[dev,ml,viz]"
python -m pip check
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src/motion
python -m pytest --cov=motion
python -m build
```

The ordinary suite is deterministic and does not need credentials, network
access or a running simulator.  Sanitised HERE JSON, small OSM/OpenDRIVE files,
fake CARLA actors/worlds and generated tabular samples cover external contracts.
The `viz` extra is only required for the UC-03 heatmap-rendering test; without
it, that one test is skipped (`pytest.importorskip`) and everything else runs
unaffected.

## Test layers

- `tests/characterization`: frozen numerical and behavioral outputs from the
  original implementation, including documented anomalies.
- `tests/unit`: pure policies, schemas, application services and boundary
  behavior with fakes, including UC-02/UC-03's scenario workflow, KPI,
  heatmap and CLI wiring. `tests/support` holds fakes shared across those
  modules (`FakeSimulator`, `FakeTrafficProvider`, `FakeDeviceProvider`) so
  UC-02/UC-03 tests don't duplicate UC-01's own.
- `tests/integration`: filesystem/model/data flows that remain offline.

The GitHub Actions workflow runs this offline gate on Python 3.12. The current
suite contains no live CARLA, HERE or Overpass tests; fake boundaries verify
contracts and failure handling, not interoperability with those systems.

## Coverage interpretation

Coverage uses branch tracking and a configured minimum of 68%. It measures the
offline suite only and is not evidence of live interoperability with CARLA,
HERE or Overpass.
