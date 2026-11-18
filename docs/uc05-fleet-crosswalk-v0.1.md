# UC-05 — Candidate ACI–ISPRA–COPERT fleet crosswalk

## Scope

This document describes a candidate method for converting vehicle-fleet data
into profiles compatible with COPERT 5.9.2. The profiles weight the emission
factors of individual technologies to obtain a mean factor for each vehicle
category observed by FRONTIERE.

The crosswalk is an offline preparation step, outside the UC-05 runtime flow.
The proposed runtime receives passage counts, selects previously prepared
emission factors and calculates emissions for the segment and interval.

The method has not been scientifically approved. Its rules provide a
reproducible basis that can be replaced or calibrated when more representative
local observations become available. The rules and preliminary results below
refer to method version 0.1, documented on 21 August 2026.

## Data sources

| Source | Role in the method | Main limitation |
|---|---|---|
| ACI Open Parco Veicoli, Salerno 2024 | Local registered stock by category, fuel and Euro class. | Registered stock does not necessarily represent the vehicles travelling through Baronissi. |
| ISPRA, `DatiCopertTrasportoStrada1990-2024.xlsx`, based on COPERT 5.8.1 | National activity/VKT shares used to disaggregate dimensions absent from ACI data. | A national proxy does not directly describe local traffic. |
| COPERT 5.9.2 Tier 3 | Hot tailpipe emission factors by technology and speed. | Requires a configured fleet and driving conditions; outputs need validation for project use. |
| FRONTIERE | Passage counts classified into observable vehicle categories. | The actual taxonomy, count quality and treatment of ambiguous classes remain to be confirmed. |

ISPRA 5.8.1 data are used only to compose the fleet. Emission factors are not
converted from COPERT 5.8.1 to 5.9.2: they are recalculated directly with
COPERT 5.9.2.

## Mapping types

| Status | Meaning |
|---|---|
| `DIRECT` | The source classification is compatible with the required COPERT family. |
| `PROXY` | The mapping uses an explicit approximation. |
| `CONDITIONAL` | The rule depends on the taxonomy FRONTIERE makes available. |
| `UNMAPPED` | No usable mapping is available; the corresponding share must remain reported. |

Status applies to an individual dimension. A category can map directly while
engine displacement, mass or COPERT segment is assigned through a proxy.

## Vehicle categories

| MOTION category | Expected COCO ID | ACI 2024 source | Salerno stock | Candidate rule |
|---|---:|---|---:|---|
| `CAR` | 2 | `AV` — Passenger cars | 737,963 | Use the entire AV category. |
| `MOTORCYCLE` | 3 | `MC` — Motorcycles | 138,710 | Use MC; inclusion of mopeds depends on FRONTIERE semantics. |
| `BUS` | 5 | `AB` — Buses | 2,233 | Use the entire AB category. |
| `TRUCK` | 7 | `AM` — Goods vehicles + `TS` — Road tractors | 94,162 | Build an aggregated LCV/HDT profile while FRONTIERE exposes a single `truck` class. |
| `SPECIAL_TBD` | — | `AS` — Special-purpose vehicles | 15,991 | Keep separate; do not include automatically in `TRUCK`. |

### FRONTIERE taxonomy options

- If FRONTIERE exposes only `truck`, UC-05 uses the aggregated `TRUCK` profile
  built from AM and TS.
- If FRONTIERE distinguishes light and heavy commercial vehicles, separate
  `TRUCK_LCV` and `TRUCK_HDV` profiles can be created.
- If FRONTIERE includes special-purpose vehicles in `truck`, incorporating AS
  requires a new profile version.
- If `motorcycle` includes mopeds, the profile needs moped segments from an
  additional source: the available ACI MC dataset covers motorcycles above
  50 cm³.

## Fuels and powertrains

The candidate rules below retain the approximations marked as proxies in the
resulting profile.

| ACI codes | Interpretation in the COPERT profile | Note |
|---|---|---|
| `BE` | Petrol | Direct for CAR, MOTORCYCLE and TRUCK; proxy for BUS. |
| `GA`, `GG` | Diesel | `GA` maps directly for CAR, BUS and TRUCK; the other cases are proxies. |
| `EL` | Battery Electric | Zero contribution within the hot tailpipe CO₂ boundary; this does not imply zero life-cycle emissions. |
| `BG`, `IBG` | LPG Bifuel for CAR; Petrol for the other profiles | The hybrid component is not represented when no equivalent technology exists. |
| `BM`, `IBM`, `IM`, `ME` | CNG/CNG Bifuel where available | Combining technologies is a proxy when COPERT does not expose the ACI granularity. |
| `IB` | Petrol Hybrid for CAR; Petrol for the other profiles | Direct only for CAR. |
| `IG` | Diesel Hybrid for BUS; Diesel for the other profiles | Not automatically interpreted as Diesel PHEV. |
| `IGG`, `IGM` | Diesel | Conservative proxy. |
| `AL` | Petrol for MOTORCYCLE; unmapped for the other profiles | The motorcycle mapping preserves the share but requires validation. |
| `ND` | Unmapped | Neither converted to zero nor silently discarded. |

### Fuel-mapping coverage

| Category | Direct | Proxy | Unmapped |
|---|---:|---:|---:|
| `CAR` | 99.297% | 0.699% | 0.004% |
| `MOTORCYCLE` | 93.752% | 6.245% | 0.002% |
| `BUS` | 99.060% | 0.940% | 0.000% |
| `TRUCK` | 96.473% | 3.524% | 0.003% |

These percentages describe fuel mapping only. They exclude the approximations
required for mass, engine displacement, bus type or COPERT segment.

## Euro classes

COPERT groups some regulatory stages at a different granularity from ACI. The
public ACI legend consulted also does not formally decode the `5B` and
`6A`–`6E` suffixes. These correspondences remain working mappings to be
confirmed with ACI or ISPRA.

| ACI label | Passenger Cars / LCV | HDT / BUS | L-Category | Status |
|---|---|---|---|---|
| `EURO 0` | Compatible pre-Euro stages / `Conventional` | `Conventional` | `Conventional` | Proxy for passenger cars; direct mapping to `Conventional` in the other cases. |
| `EURO 1`–`EURO 4` | `Euro 1`–`Euro 4` | `Euro I`–`Euro IV` | `Euro 1`–`Euro 4` | Direct. |
| `EURO 5` | `Euro 5` | `Euro V` | `Euro 5` | Direct at COPERT granularity. |
| `EURO 5B` | `Euro 5` | `Euro V` | `Euro 5` | Grouped; ACI suffix remains to be confirmed. |
| `EURO 6` | Split across `Euro 6 a/b/c`, `6 d-temp`, `6 d/e` | Split across `Euro VI A/B/C` and `VI D/E` | `Euro 5` | Proxy split using ISPRA shares. |
| `EURO 6A`–`EURO 6C` | `Euro 6 a/b/c` | `Euro VI A/B/C` | `Euro 5` | Working mapping; proxy grouping for L-Category. |
| `EURO 6D` | `Euro 6 d-temp` | `Euro VI D/E` | `Euro 5` | Working mapping; proxy grouping for L-Category. |
| `EURO 6E` | `Euro 6 d/e` | `Euro VI D/E` | `Euro 5` | Working mapping; proxy grouping for L-Category. |
| `NC` with `EL` | Zero hot tailpipe | Zero hot tailpipe | Zero hot tailpipe | Valid only within the declared emissions boundary. |
| Non-electric `NC` | — | — | — | Unmapped. |
| `ND` | Conditional ISPRA Euro distribution | Conditional ISPRA Euro distribution | Conditional ISPRA Euro distribution | Proxy; if fuel is also ND, the record remains unmapped. |

## Fleet weights

ACI does not expose every dimension required by COPERT. For each
`category × fuel × Euro` cell, ISPRA activity shares distribute the stock
among compatible segments:

- `CAR`: Mini, Small, Medium, Large/SUV/Executive;
- `MOTORCYCLE`: available engine-cycle and displacement classes;
- `BUS`: urban/coach and size classes;
- `AM`: LCV and rigid HDV;
- `TS`: articulated HDV.

To avoid double allocation, AM does not contribute to articulated segments and
TS does not contribute to rigid segments.

Let $S^{ACI}_{c,f,e}$ be the ACI stock and $p^{ISPRA}_{i\mid c,f,e}$ the ISPRA
activity share for technology $i$:

$$
q_{c,i}=S^{ACI}_{c,f,e}\,p^{ISPRA}_{i\mid c,f,e}
$$

$$
w_{c,i}=\frac{q_{c,i}}{\sum_i q_{c,i}}
$$

For each vehicle category, $\sum_i w_{c,i}=1$. The weights are activity-oriented
but remain a proxy because they combine provincial stock with national VKT
shares.

When the exact ISPRA combination is missing, the proposal uses, in order:

1. the same category, fuel and Euro class;
2. the same category and fuel, with the ISPRA 2024 Euro distribution;
3. for BEVs, a virtual technology with zero hot tailpipe CO₂ contribution;
4. `UNMAPPED` when no usable correspondence is available.

There is no implicit fallback between different fuels.

## Preliminary mapping results

Applying these rules to the Salerno 2024 snapshot produced the following
results. They document the working design and do not scientifically validate
the representativeness of the fleet.

| Category | Source stock | Mapped stock | Direct | Proxy | Conditional | Unmapped | Resulting technologies |
|---|---:|---:|---:|---:|---:|---:|---:|
| `CAR` | 737,963 | 737,937 | 54.997% | 38.938% | 6.062% | 0.004% | 130 |
| `MOTORCYCLE` | 138,710 | 138,707 | 93.675% | 6.323% | 0.000% | 0.002% | 25 |
| `BUS` | 2,233 | 2,233 | 78.818% | 10.255% | 10.927% | 0.000% | 49 |
| `TRUCK` | 94,162 | 94,156 | 70.111% | 19.504% | 10.378% | 0.006% | 138 |

The resulting fuel and powertrain mix is:

| Category | Profile composition |
|---|---|
| `CAR` | Diesel 49.018%; Petrol 35.939%; LPG Bifuel 9.357%; CNG Bifuel 3.059%; Petrol Hybrid 2.311%; Battery Electric 0.316%. |
| `MOTORCYCLE` | Petrol 99.765%; Battery Electric 0.235%. |
| `BUS` | Diesel 99.328%; CNG 0.493%; Battery Electric 0.179%. |
| `TRUCK` | Diesel 92.952%; Petrol 5.161%; CNG 1.724%; Battery Electric 0.164%; LCV 55.006% and HDV 44.994%. |

The LCV/HDT share comes from the national ISPRA proxy. It is not a measurement
of local traffic in Salerno or Baronissi.

## Emission factors from fleet weights

For each COPERT technology $i$, weight $w_{c,i}$ is applied to its hot tailpipe
CO₂ factor. The mean factor for a vehicle category is:

$$
EF_c(v)=\sum_i w_{c,i}\,EF_i(v)
$$

Here, $v$ is the representative speed for the segment and interval. BEVs
remain in the profile denominator with a zero hot tailpipe contribution.

The candidate method generates an emission-factor matrix offline over a speed
grid. Runtime processing selects the corresponding value or, if approved,
interpolates between nodes. Changes to fleet composition, taxonomy or COPERT
conditions require regenerated profiles and factors, not a COPERT call for
each 15-minute interval.

The preliminary proof of concept is documented in
[`artifacts/reference/copert-poc-592/README.md`](../artifacts/reference/copert-poc-592/README.md).
It tests the COPERT input/output flow but does not represent the weighted
ACI/ISPRA profile described here.

## Assumptions and open issues

1. Confirm the FRONTIERE data dictionary, particularly `truck` semantics,
   any LCV/HDT distinction and the inclusion of mopeds.
2. Confirm the interpretation of `EURO 5B` and `EURO 6A`–`EURO 6E` with ACI
   or ISPRA.
3. Assess whether the ACI stock × ISPRA VKT proxy represents local activity
   and, where possible, calibrate it with observed traffic in Baronissi.
4. Decide whether and how to include special-purpose vehicles in `TRUCK`.
5. Approve the COPERT version, hot tailpipe boundary, profiles, speed grid,
   interpolation and handling of speeds outside the domain.
6. Define a validation protocol and sensitivity analysis before treating the
   factors as suitable for operational use.

## Sources

- ACI Open Parco Veicoli, Salerno 2024 snapshot for AV, MC, AB, AM, TS and AS.
- [ACI Open Parco Veicoli — category and fuel legend](https://opv.aci.it/WEBDMCircolante/legenda.html).
- [ACI Open Parco Veicoli — methodological notes](https://opv.aci.it/WEBDMCircolante/noteOPV.html).
- ISPRA, `DatiCopertTrasportoStrada1990-2024.xlsx`, `veickm` sheet, based on
  COPERT 5.8.1.
- [EMEP/EEA Road Transport Guidebook 2024](https://copert.emisia.com/wp-content/uploads/2024/07/1.A.3.b.i-iv-Road-transport-2024.pdf).
- [Regulation (EU) No 459/2012](https://eur-lex.europa.eu/eli/reg/2012/459/oj/eng), Euro 5a/5b and 6a/6b/6c stages.
- [Regulation (EU) 2017/1347](https://eur-lex.europa.eu/eli/reg/2017/1347/oj/eng) and the [consolidated text of Regulation 2017/1151](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02017R1151-20200125), Euro 6d-TEMP and 6d stages.
- COPERT 5.9.2, the Windows installation used for project tests.
