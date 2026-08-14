# Software archaeology and migration record

## Recovered baseline

The original repository was a flat collection of executable Python files.  Its
primary workflow selected a HERE-covered road, downloaded OSM data through
Overpass, converted it to OpenDRIVE, repaired known XML defects, generated a
CARLA world and refreshed simulated traffic from HERE every 60 seconds.  A
synthetic field-device feed provided count and speed observations when segment
traffic was unavailable.

A separate experimental flow collected CARLA vehicle telemetry into CSV files,
enriched it with jam/collision labels, trained a Random Forest classifier and
performed per-vehicle real-time inference. The reference Torino OSM/OpenDRIVE pair
and serialized model were retained as reference artifacts.

Execution was split across root-level scripts. One monolithic traffic-mirroring
script combined configuration, domain calculations, HTTP, projection, CARLA
lifecycle, population, control, sanitisation and output. Separate scripts performed map
conversion, telemetry collection, enrichment, training and inference. Those
filenames remain in Git history; they are not current entry points.

## Main findings

| Finding | Risk | Migration response |
|---|---|---|
| Import-time environment and filesystem assumptions | Imports could fail or mutate local state. | Settings are loaded only at the composition root; imports are side-effect free. |
| `.env` mixed credentials with generated map state | Configuration was overwritten and state had no schema or atomicity. | Static settings remain in `.env`; map state moved to versioned, atomic JSON. |
| A 15-second client timeout remained inside the mirror despite 120-second checks | Full OpenDRIVE world generation could time out unpredictably. | One 120-second configured CARLA timeout is used at the lifecycle boundary. |
| Verification and mirror paths regenerated worlds repeatedly | Slow, failure-prone startup and inconsistent checks. | Provision once, register only after validation, then load the same artifact. |
| Cleanup selected every CARLA vehicle | A mirroring-session shutdown could destroy external actors. | Explicit session ownership controls all destruction. |
| HERE request exceptions could include credential-bearing URLs | Secret disclosure in errors/logs. | Adapter errors contain endpoint purpose/status, never API query strings. |
| Collector omitted `weather_rain` while training required it | The advertised ML workflow could not execute end to end. | Telemetry schema and dataset builder make weather handling explicit. |
| Label shift was applied after a grouped transform | A vehicle could inherit another vehicle's future incident label. | Rolling and shift occur within the same vehicle/session group. |
| README claimed a session split, code used random rows | Temporal/session leakage could inflate metrics. | Session-aware grouped split is used when session metadata exists; legacy fallback is reported. |
| Current classifier was described near traffic forecasting | A per-vehicle risk experiment could be mistaken for UC-04. | Prediction package and UC catalog explicitly separate the two contracts. |
| Machine-specific Windows paths and duplicated literals | Poor portability and configuration drift. | `pathlib`, project-root discovery and typed settings centralise paths/values. |
| No tests, package metadata or CI | Refactoring had no regression gate. | Layered offline tests, Ruff, mypy, packaging and GitHub Actions were added. |

The MOTION use-case scope spans vehicle analysis, simulation, environmental
monitoring and decision support. [The use-case catalog](use-cases.md) records
current implementation status and separates research intent from executable
repository behavior.

Current package ownership is documented in [architecture.md](architecture.md),
and retained/corrected behaviors are listed in
[non-regression.md](non-regression.md). Obsolete implementations and temporary
root-level wrappers were removed once their supported workflows were available
through the installed CLI. The Torino maps and pinned legacy model remain under
`data/reference` and `artifacts/reference` with explicit provenance limits.
