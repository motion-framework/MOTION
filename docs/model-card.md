# Model card — OR3 behavioral incident risk

## Identity and intended use

The model estimates binary risk for individual vehicles in CARLA experiments
from vehicle speed and driving controls. It is a separate OR3 behavioral
research capability: it does not implement UC-04 (multivariate traffic
prediction), UC-06 or UC-07, does not predict road-network state and is not a
safety-critical component.

Ordered features:

```text
speed_kmh, throttle, brake, steer, weather_rain
```

Declared target: `incident_detected`, a heuristic derived from collisions,
immobility and deceleration. Current schema: `1.0.0`.

## Legacy reference artifact

The `artifacts/reference/models/traffic_aimodel.pkl` artifact is retained as a
historical reference, not as a reproducible result of the current pipeline. Its
digest was verified before controlled deserialization; the properties below
were obtained by inspecting the estimator. Provenance is also available in
[machine-readable form](../artifacts/reference/models/traffic_aimodel.metadata.json).

| Property | Verified value |
|---|---|
| SHA-256 | `f938acd67bb0fda0b63027865167564452331fb692d80aba9ad820515cfbeec2` |
| Size | 16,294,105 bytes |
| Git blob | `971f7c20eb30bbc0706e817159b486966092579d` |
| Introduction commit | `11dc9cc540d053905489a4f6189e7e9756c68e39` |
| Format | joblib/pickle, outer protocol 4 with embedded NumPy arrays |
| Estimator | `sklearn.ensemble.RandomForestClassifier` |
| scikit-learn version recorded in pickle | `1.9.0` |
| Recorded samples | 87,718 |
| Classes | `[0, 1]` |
| Trees / depth / leaf | 100 / 15 / 5 |
| Split / max features / bootstrap | 2 / `sqrt` / `True` |
| Random state | 42 |
| Class weight | `balanced` |

Two sample weights are present: `1.7217162597157887`, repeated 25,474 times,
and `0.7046301651564809`, repeated 62,244 times. This establishes the multiset
of counts `{25,474, 62,244}`, but without the dataset neither count can be
reliably assigned to a label.

## Provenance discrepancy

The versioned training script specifies `n_estimators=100`, `max_depth=15`,
`min_samples_leaf=5` and `random_state=42`, but does not set `class_weight`; its
default is therefore `None`. The reference artifact instead contains
`class_weight="balanced"`.

This discrepancy prevents attribution of the pickle to the committed script.
The current pipeline does not attempt to reconstruct missing parameters;
current training retains `class_weight=None`, which is the script's contract.
The original dataset, sessions, maps, scenarios, training command, manifest and
offline metrics are unavailable, so the legacy artifact cannot be reproduced
from the repository.

The historical requirements declared joblib 1.5.3, NumPy 2.3.4, pandas 2.3.3
and scikit-learn 1.9.0. Only the scikit-learn version embedded in the pickle is
demonstrated by the artifact.

## Limitations and risks

- The target uses look-ahead and is not independent ground truth.
- The final 15 rows for each vehicle are censored but marked as negative
  (`legacy_zero_tail`).
- `delta_speed` is not normalized by time; changing the sampling frequency
  changes the threshold semantics.
- `weather_rain` is absent from the legacy collector, so the historical flow
  could not run end to end without an undocumented source or default.
- Coverage across scenarios, vehicle types, maps and weather/traffic conditions
  is not documented; neither are probability calibration or out-of-domain
  tests.
- Training and the real-time tracker use different outcomes: the target combines
  collision, immobilization and deceleration, whereas the tracker confirms an
  event using hard braking (`brake > 0.8`) and near standstill
  (`speed_kmh < 2`).
- The legacy script's random row split may leak information. The current
  pipeline splits by session when `session_id` is available; its explicit row
  fallback is permitted only when that column is absent.
- The joblib/pickle format can execute code during loading. A digest verifies
  integrity, not authenticity; load only trusted artifacts whose hash has been
  pinned through a separate channel.

## Minimum requirements for further use

Further use requires versioned datasets and manifests, independent
train/validation/test sessions, an annotation protocol or external ground
truth, evaluation by scenario and class, confidence intervals, error analysis,
calibration, drift tests and validation against the same outcome definition
used at runtime. Until then, the model should be treated solely as a CARLA
research prototype.
