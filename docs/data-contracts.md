# Data contracts for the OR3 behavioral pipeline

## Scope

The `motion.prediction` pipeline is an OR3 behavioral research
capability. It neither implements nor demonstrates Macro Use Cases UC-04,
UC-06 or UC-07. Core code does not open CARLA connections, access the network,
or read or write files on import; paths are always supplied by the caller.

The current feature schema version is `1.0.0`. Feature order is part of the
contract and cannot change without a new version:

```text
speed_kmh, throttle, brake, steer, weather_rain
```

The binary target is `incident_detected`.

## Raw observations

Each row represents one vehicle sample. Temporal groups in the master dataset
are always identified by `(session_id, v_id)`.

| Field | Type/unit | Constraint and provenance |
|---|---|---|
| `session_id` | string | Non-empty. Identifies an independent simulation session. The builder uses the value in the CSV or, when absent, derives it from the filename. A file must describe exactly one session. |
| `timestamp` | seconds | Finite; defines temporal order within a group. Sampling frequency and clock must be recorded in provenance. |
| `v_id` | string or integer | Non-null and non-empty vehicle identifier, meaningful only within its session. |
| `x`, `y` | CARLA world meters | Finite coordinates in the same reference system as the session. |
| `speed_kmh` | km/h | Finite and greater than or equal to zero. |
| `throttle` | fraction | Range `[0, 1]`. |
| `brake` | fraction | Range `[0, 1]`. |
| `steer` | normalized control | Range `[-1, 1]`. |
| `weather_rain` | CARLA percentage | Range `[0, 100]`; required feature column. |
| `collision` | binary | `0` or `1`. In the current CARLA collector the value remains `1` after the first collision; another producer must declare its semantics explicitly. |

`weather_rain` is never inferred. If the column or any cells are missing,
dataset construction fails unless the caller explicitly supplies a default,
including an intentional `0.0`. The manifest records the default, the number
of replaced cells and the hashes of the source files. Existing values that are
non-numeric, infinite or outside the accepted range cause failure even when a
default is available; the builder performs no silent clipping or replacement.

## Enrichment and labels

Rows are stably sorted by group, `timestamp` and input order; the result is then
returned in its original order. Legacy thresholds use strict inequalities:

- `is_stuck = 1` when the maximum over a complete 10-sample window is
  `< 0.5 km/h`;
- `jam_by_crash = 1` for a stuck vehicle without a collision at a distance of
  `< 15 m` from a collision position in the same session;
- `jam_normal = is_stuck AND NOT jam_by_crash AND NOT collision`;
- `base_incident = collision OR is_stuck`;
- `delta_speed` is the sample-to-sample difference within the same group, and
  `delta_speed < -8 km/h` forces the target to `1`.

Collision positions used by `jam_by_crash` come from the entire session,
including future rows. This look-ahead is legacy behavior and makes the
transformation unsuitable for causal streaming.

The primary label is calculated independently for each `(session_id, v_id)`:

```text
rolling_max(base_incident, window=20, min_periods=1)
-> shift(-15) within the same group
-> fillna(0)
```

The shift never crosses a vehicle or session boundary. The formula does not
simply mean “incident within 15 samples”: for row `i`, it covers `i-4 ... i+15`,
truncated at group boundaries. With regular 0.5-second samples, this corresponds
to 2 seconds of history and 7.5 seconds of future data. The final 15 rows for
each vehicle are censored but labeled `0`; this policy is recorded as
`legacy_zero_tail`, not as an independent negative observation.

This label is a heuristic constructed from collisions, immobility and speed
variation. It is not independently annotated ground truth and does not alone
support scientific claims about predictive performance or safety.

## Dataset files and manifests

```python
build_dataset_files(
    inputs: Sequence[Path],
    output: Path,
    *,
    weather_rain_default: float | None = None,
) -> DatasetBuildResult
```

The builder rejects duplicate inputs, duplicate session IDs, empty files and
outputs that overwrite an input. It produces the CSV and
`<output>.metadata.json`. The manifest contains the version, dataset SHA-256,
counts, sessions, weather/tail policies, enrichment parameters and, for each
source, only its filename, SHA-256, row count and number of replaced weather
cells. Personal paths are not embedded in the manifest.

## Training and evaluation

The `dataset build` command always introduces `session_id`. When the column is
present, sorted sessions are assigned in their entirety to either training or
test data; the sets are disjoint and independent of row/file order. The
function fails when fewer than two sessions are available. A random row-level
split, deterministic with seed `42`, is used only when an external or legacy
dataset without `session_id` is passed directly to the trainer. This fallback
is scientifically weaker because it can leak temporal information or
information between correlated vehicles.

Training requires both classes in the training set. The confusion matrix always
uses `labels=[0, 1]`; accuracy, precision, recall and F1 use
`zero_division=0`.

The current classifier is:

```text
RandomForestClassifier(
  n_estimators=100,
  max_depth=15,
  min_samples_leaf=5,
  random_state=42,
  class_weight=None
)
```

Other parameters retain the defaults of the scikit-learn version recorded in
the metadata. `class_weight=None` preserves the versioned training script; the
legacy reference instead uses `balanced`, as documented in the model card.

## Artifacts

`train_model_file(dataset_path, output_path)` returns metrics, split information
and paths to three files:

```text
<model>                 joblib model
<model>.metadata.json   schema, parameters, versions, metrics and provenance
<model>.sha256          model checksum
```

The repository first reads and validates the JSON, calculates the SHA-256 as a
stream, compares the JSON value, sidecar and any digest pinned through a
separate channel, and only then calls `joblib.load`. After loading, it checks
the model type, feature count/order, classes and parameters. SHA-256 detects
corruption, not authenticity: replacing the model and sidecar together remains
dangerous. Joblib/pickle artifacts should be loaded only from trusted sources,
preferably using a digest distributed separately.

The raw legacy model is supported only through the explicit
`load_trusted_legacy_model(path, expected_sha256=...)` API, which always
requires a separately provided hash before deserialization and cannot
reconstruct missing metadata.

## Inference and tracker

`predict_incident(model, VehicleObservation(...))` performs one inference,
preserves canonical feature order and propagates estimator failures. It does
not access CARLA, files, the clock or the network.

The tracker is a pure transition: `state + sample -> new state + events`. It
retains legacy semantics: an alert opens for positive risk with at least one
nearby vehicle, is confirmed by `brake > 0.8` and `speed_kmh < 2`, and expires
strictly after more than 8 seconds. Confirmation is evaluated before expiry.
One intentional correction makes every sample act as a heartbeat that expires
alerts for vehicles that have disappeared, preventing indefinitely stale
state. The caller measures and supplies inference latency explicitly.
