# Torino map reference snapshot

These files were present in the original repository and are retained as
inspectable research snapshots, not as generated runtime
output:

- `torino_map.osm` - OpenStreetMap XML snapshot (1,690 nodes, 236 ways and 63
  relations in the recorded baseline).
- `torino_map.xodr` - CARLA/OpenDRIVE derivative (103 roads, 26 junctions, 202
  geometries, 4 objects and 6 signals in the recorded baseline).

Baseline SHA-256 digests:

```text
55bfba115b7b2a6ade133fb1f8943b23d93fa3df7d877cd1efca4aa6e2185b0a  torino_map.osm
f077841e218633cf7edb40581072f56945478697afc81f985a15e87967a87fef  torino_map.xodr
```

The repository history does not identify the exact OSM extraction timestamp,
query or downstream conversion command. Do not present this snapshot as
reproducible until that provenance is recovered. OpenStreetMap data is subject
to the ODbL; see the project `NOTICE.md`.
