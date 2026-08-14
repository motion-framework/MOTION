"""Structured inspection of OpenStreetMap extracts."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OsmBounds:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    source: str


@dataclass(frozen=True, slots=True)
class OsmInspection:
    path: Path
    node_count: int
    way_count: int
    relation_count: int
    bounds: OsmBounds | None


def inspect_osm(path: Path) -> OsmInspection:
    root = ET.parse(path).getroot()
    if root.tag != "osm":
        raise ValueError(f"Expected <osm> root in {path}, found <{root.tag}>")
    nodes = root.findall("node")
    bounds_element = root.find("bounds")
    bounds: OsmBounds | None = None
    if bounds_element is not None:
        try:
            bounds = OsmBounds(
                min_lat=float(bounds_element.attrib["minlat"]),
                min_lon=float(bounds_element.attrib["minlon"]),
                max_lat=float(bounds_element.attrib["maxlat"]),
                max_lon=float(bounds_element.attrib["maxlon"]),
                source="bounds_tag",
            )
        except (KeyError, ValueError) as error:
            raise ValueError(f"Invalid <bounds> element in {path}") from error
    elif nodes:
        try:
            latitudes = [float(node.attrib["lat"]) for node in nodes]
            longitudes = [float(node.attrib["lon"]) for node in nodes]
        except (KeyError, ValueError) as error:
            raise ValueError(f"Invalid OSM node coordinates in {path}") from error
        bounds = OsmBounds(
            min_lat=min(latitudes),
            min_lon=min(longitudes),
            max_lat=max(latitudes),
            max_lon=max(longitudes),
            source="node_extent",
        )
    return OsmInspection(
        path=path,
        node_count=len(nodes),
        way_count=len(root.findall("way")),
        relation_count=len(root.findall("relation")),
        bounds=bounds,
    )
