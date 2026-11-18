# UC-05 candidate emissions methodology

## Scope

This candidate method estimates vehicle-related CO₂ mass for a road segment
and time interval from observed traffic data. It provides methodological
support for UC-05; it is not a runtime use case.

COPERT is not the only admissible method. An approved alternative may be used
provided the following remain explicit and compatible:

- formula, units and emissions boundary;
- supported vehicle categories;
- emission factors or function and their applicability domain;
- sources, version, geographic scope and reference period;
- assumptions, limitations and approval status.

The result is an estimated emissions mass, not an atmospheric concentration
measurement or an air-quality forecast.

## Emissions boundary

The proposed baseline estimates hot tailpipe CO₂: exhaust emissions from an
engine at operating temperature. Unless an extension is explicitly approved,
it excludes:

- cold starts;
- evaporative emissions;
- upstream energy and fuel production;
- vehicle life-cycle emissions;
- CO₂ equivalents for other greenhouse gases.

This boundary matches the `CO2_HOT` output checked in the COPERT 5.9.2
proof of concept (POC) and does not require the runtime to supply information
unavailable from field devices.

## Runtime calculation

For each vehicle category `c`:

```text
A_c = N_c × d_c          [vehicle-km]
E_c = A_c × EF_c(v_c)    [gCO₂]
E   = Σ_c E_c           [gCO₂]
```

Here:

- `N_c` is the number of unique vehicle passages in category `c` during
  the interval;
- `d_c` is the distance attributed to each passage, in km;
- `A_c` is category activity, in vehicle-km;
- `v_c` is the category's representative speed;
- `EF_c(v_c)` is its mean emission factor at that speed, in
  gCO₂/(vehicle-km);
- `E_c` is the estimated mass for the category;
- `E` is the estimated total mass for the interval.

The current proposal sets `d_c` to the length of the segment associated with
the device. Each counted passage is therefore assumed to traverse the entire
segment. This assumption needs reassessment where there are ramps,
intermediate access points or multiple detection points.

When the field provides a mean speed for each category, UC-05 uses `v_c`.
When it provides only one representative segment speed, the same `v` is
applied to all categories in the interval. The result metadata must identify
which speed representation was used.

The window duration delimits the passages counted; it is not an additional
multiplier. Activity is already expressed by `N_c × d_c`.

## Required observations

The proposed input is the validated traffic observation produced by UC05-01:

- device and segment identifiers;
- travel direction;
- interval start and end;
- unique passage counts by category;
- mean speed by category or representative segment speed;
- available completeness and quality indicators.

The candidate categories are `CAR`, `MOTORCYCLE`, `BUS` and `TRUCK`.
If FRONTIERE confirms the standard COCO taxonomy, the candidate references are
`car/2`, `motorcycle/3`, `bus/5` and `truck/7`. The actual classes and
the meaning of `truck` remain subject to confirmation with the partner.

## Offline fleet preparation

### Sources

The POC configuration combines:

1. ACI Open Parco Veicoli 2024 for the province of Salerno: registered stock by
   vehicle category, fuel and Euro class.
2. ISPRA's `DatiCopertTrasportoStrada1990-2024.xlsx`, sheet `veickm`:
   national activity/VKT shares for dimensions absent from ACI.
3. COPERT 5.9.2 Tier 3: hot tailpipe CO₂ factors under the POC driving
   conditions.

ACI describes the registered fleet at 31 December, not the traffic observed
in Baronissi. ISPRA supplies a national activity proxy. The result is therefore
an activity-profile proxy, not the established composition of vehicles passing
through a site during a particular time band.

### ACI stock used in the POC

| UC-05 category | ACI Salerno stock, 2024 | Source rule |
|---|---:|---|
| CAR | 737,963 | Passenger cars (AV) |
| MOTORCYCLE | 138,710 | Motorcycles (MC) |
| BUS | 2,233 | Buses (AB) |
| TRUCK | 94,162 | Goods vehicles (AM) + road tractors (TS) |
| SPECIAL_TBD | 15,991 | Special-purpose vehicles (AS), excluded from v0.1 |

TRUCK combines light and heavy commercial vehicles because the candidate
runtime taxonomy contains a single `truck` class. A finer classification
would require a new mapping and new category-average factors.

The [fleet crosswalk](uc05-fleet-crosswalk-v0.1.md) records the full mapping,
assumptions and reconciliation checks.

### Fleet weights

For COPERT technology `i` in category `c`, fuel `f` and Euro class `e`:

```text
q_(c,i) = S_ACI_(c,f,e) × p_ISPRA_(i | c,f,e,2024)
w_(c,i) = q_(c,i) / Σ_j q_(c,j)
```

Here:

- `S_ACI_(c,f,e)` is the local ACI stock;
- `p_ISPRA_(i | c,f,e,2024)` is the conditional ISPRA vehicle-km share;
- `w_(c,i)` is the normalised technology weight within the category profile.

For each category, `Σ_i w_(c,i) = 1`. These weights describe fleet composition;
they are not emission factors. Fuel, Euro class, mass or engine capacity and
subcategory remain represented through the weighted COPERT technologies.
Electric vehicles remain in the profile denominator and contribute zero hot
tailpipe CO₂.

No emission-factor conversion from COPERT 5.8.1 to 5.9.2 is performed.
ISPRA/COPERT 5.8.1 supplies the composition and activity proxy; factors are
calculated directly with COPERT 5.9.2.

## COPERT factor generation

The POC uses:

- COPERT 5.9.2, Tier 3;
- the `Urban Off Peak` environment;
- 0% road gradient;
- 50% HDT/BUS load;
- seven speeds: 10, 20, 30, 40, 50, 60 and 70 km/h;
- hot tailpipe CO₂ outputs aggregated into the four UC-05 categories.

Normalised weights are converted into synthetic fleets with the same mean
activity per technology. For each category, the denominator is:

```text
D_c = 10^6 vehicles × 10^4 km/vehicle = 10^10 vehicle-km
```

If `T_(c,i)(v)` is the hot CO₂ mass in tonnes produced by COPERT for technology
`i`, the category-average factor is:

```text
EF_c(v) = [Σ_i T_(c,i)(v) × 10^6 g/t] / 10^10 vehicle-km
```

The original analysis references an
[input package and execution script](../artifacts/analysis/uc05/copert-592-ef-package-v0.1.2/README.md)
and a
[results package describing the aggregation procedure](../artifacts/analysis/uc05/copert-592-ef-results-v0.1/README.md).
These generated analysis files are not tracked in the repository.

## POC emission factors

Values are expressed in gCO₂/(vehicle-km):

| Speed (km/h) | CAR | MOTORCYCLE | BUS | TRUCK |
|---:|---:|---:|---:|---:|
| 10 | 273.68 | 234.51 | 1,930.66 | 852.67 |
| 20 | 200.02 | 145.74 | 1,321.68 | 636.25 |
| 30 | 166.22 | 113.42 | 1,006.54 | 509.22 |
| 40 | 147.64 | 99.11 | 833.20 | 431.64 |
| 50 | 137.20 | 93.09 | 725.43 | 383.53 |
| 60 | 131.90 | 91.83 | 656.82 | 357.29 |
| 70 | 130.29 | 93.82 | 616.58 | 349.35 |

The analysis references the full machine-readable table as
[`UC05_COPERT_592_AGGREGATED_EF_v0.1.csv`](../artifacts/analysis/uc05/copert-592-ef-results-v0.1/UC05_COPERT_592_AGGREGATED_EF_v0.1.csv).

Higher factors at low speeds follow from the empirical speed–consumption and
emissions curves used by the Tier 3 method. No manual coefficient based on
time spent on the segment was added.

## Runtime factor selection

Between two grid speeds, the proposal uses linear interpolation:

```text
EF_c(v) = EF_c(v_i)
        + [(v - v_i) / (v_(i+1) - v_i)]
        × [EF_c(v_(i+1)) - EF_c(v_i)]
```

The 10–70 km/h grid is the range checked in the POC, not an intrinsic COPERT
limit. Before operational use, one of the following policies must be approved:

- extend the grid to cover the segment's realistic speeds;
- explicitly approve a rule for values outside the domain;
- report the estimate as unavailable when no applicable factor exists.

There is no implicit fallback.

## Worked example

Assumptions:

- complete observation window: 15 minutes;
- segment length: 1.2 km;
- representative speed: 40 km/h for all categories;
- passages: 100 CAR, 15 MOTORCYCLE, 3 BUS and 12 TRUCK.

| Category | N_c | A_c = N_c × 1.2 | EF_c(40) | E_c |
|---|---:|---:|---:|---:|
| CAR | 100 | 120.0 vehicle-km | 147.64 | 17,717 gCO₂ |
| MOTORCYCLE | 15 | 18.0 vehicle-km | 99.11 | 1,784 gCO₂ |
| BUS | 3 | 3.6 vehicle-km | 833.20 | 3,000 gCO₂ |
| TRUCK | 12 | 14.4 vehicle-km | 431.64 | 6,216 gCO₂ |
| **Total** | **130** | **156.0 vehicle-km** | — | **28,717 gCO₂** |

The estimated total is approximately 28.72 kgCO₂ over the interval.

## Validity and approval requirements

COPERT implements the EMEP/EEA Tier 3 methodology and produces factors that
depend on vehicle characteristics and driving conditions. The POC demonstrates
technical feasibility and dimensional consistency; it does not by itself
validate the method for local use.

The main limitations are:

- provincial ACI stock used as a proxy for the passing fleet;
- national ISPRA VKT shares used for dimensions absent from ACI;
- no local profiles by time band or day type;
- an aggregated TRUCK category;
- POC assumptions for road type, load and gradient;
- field-speed granularity and quality still to be established;
- exclusion of cold starts and other non-hot-tailpipe components.

Operational use requires approval of:

1. the FRONTIERE input taxonomy and semantics;
2. the distance attributed to each passage and the full-traversal assumption;
3. the fleet profile and proxy sources;
4. the COPERT configuration and emissions boundary;
5. the speed domain and factor-selection/out-of-domain policy;
6. factor validation, update and versioning criteria.

The history produced by UC05-03 could support comparisons and refinement.
Counts by broad category alone cannot reveal fuel, Euro class, mass or engine
capacity. Updating the internal weights requires richer local data or new,
explicitly approved assumptions.

## Evidence and sources

Method version 0.1 was documented on 22 August 2026 and remains a candidate
awaiting approval.

### Analysis artifacts

The crosswalk is tracked with this document. The remaining links identify
generated analysis outputs that are not tracked in the repository.

- [ACI–ISPRA–COPERT crosswalk](uc05-fleet-crosswalk-v0.1.md)
- [COPERT 5.9.2 input package](../artifacts/analysis/uc05/copert-592-ef-package-v0.1.2/README.md)
- [Results and aggregation procedure](../artifacts/analysis/uc05/copert-592-ef-results-v0.1/README.md)
- [Aggregated EF table in CSV](../artifacts/analysis/uc05/copert-592-ef-results-v0.1/UC05_COPERT_592_AGGREGATED_EF_v0.1.csv)
- [Results manifest](../artifacts/analysis/uc05/copert-592-ef-results-v0.1/result_manifest_v0.1.json)

### External sources

- [ACI Open Parco Veicoli](https://opv.aci.it/WEBDMCircolante/)
- [ACI Open Parco Veicoli methodological notes](https://opv.aci.it/WEBDMCircolante/noteOPV.html)
- [ISPRA national emissions inventory](https://emissioni.sina.isprambiente.it/inventario-nazionale/)
- [EMEP/EEA Road Transport Guidebook](https://copert.emisia.com/wp-content/uploads/2024/07/1.A.3.b.i-iv-Road-transport-2024.pdf)
- [COPERT methodology](https://copert.emisia.com/copert/methodology/)
- [Ultralytics COCO taxonomy](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/cfg/datasets/coco.yaml)
