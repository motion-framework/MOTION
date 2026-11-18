# Third-party data and research artifacts

## CARLA

CARLA and its Python API are external software. MOTION's optional `carla` extra
installs the official client package, while the simulator remains a separate
runtime. Their use and redistribution remain subject to the licenses and
notices published by the CARLA project and its dependencies.

## OpenStreetMap data

OpenStreetMap extracts included in, or downloaded by, this project contain data
copyright OpenStreetMap contributors and are made available under the Open Data
Commons Open Database License (ODbL) 1.0. Preserve the attribution and licensing
metadata embedded in each extract and provide the attribution required by the
OpenStreetMap Foundation when using or redistributing the data.

OpenDRIVE maps derived from OpenStreetMap data may retain attribution or other
obligations from their source data. Those obligations continue to apply to the
derived maps.

## Traffic-provider data

HERE traffic responses, including archived responses, are governed by the
applicable HERE account and service terms. Recording or processing them does not
alter those terms or make the responses subject to the ODbL.

## Research artifacts and provenance

Maps, telemetry datasets, archived API responses, trained models, evaluation
reports and other generated artifacts are research outputs. Their presence in
the repository does not by itself establish that they are reproducible or that
all redistribution rights have been granted.

Reference material intended for version control belongs under `data/reference/`
or `artifacts/reference/`. Each reference artifact should be accompanied by
provenance sufficient to identify:

- its source and responsible producer;
- the creation or acquisition date;
- the generating tool, version and material configuration;
- an integrity checksum;
- the applicable license or usage terms; and
- any privacy, confidentiality or redistribution restrictions.

Artifacts without this information should be treated as unverified research
material and should not be used as evidence of reproducibility or redistributed
without a separate review.
