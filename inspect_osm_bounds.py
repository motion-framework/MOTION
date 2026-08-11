import re
import sys

from dataclasses import dataclass
from typing import Optional


_COORDINATE_PATTERN = r"[-\d.]+"
BOUNDS_TAG_PATTERN = re.compile(
    rf'<bounds\s+minlat="({_COORDINATE_PATTERN})"\s+minlon="({_COORDINATE_PATTERN})"'
    rf'\s+maxlat="({_COORDINATE_PATTERN})"\s+maxlon="({_COORDINATE_PATTERN})"'
)
NODE_LAT_LON_PATTERN = re.compile(
    rf'<node\b[^>]*\blat="({_COORDINATE_PATTERN})"[^>]*\blon="({_COORDINATE_PATTERN})"'
)


@dataclass
class DetectedBounds:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    source: str


def _bounds_from_tag(content: str) -> Optional[DetectedBounds]:
    match = BOUNDS_TAG_PATTERN.search(content)
    if match is None:
        return None

    min_lat, min_lon, max_lat, max_lon = (float(value) for value in match.groups())
    return DetectedBounds(min_lat, min_lon, max_lat, max_lon, source="bounds_tag")


def _bounds_from_node_extent(content: str) -> Optional[DetectedBounds]:
    latitudes: list[float] = []
    longitudes: list[float] = []

    for match in NODE_LAT_LON_PATTERN.finditer(content):
        latitudes.append(float(match.group(1)))
        longitudes.append(float(match.group(2)))

    if not latitudes:
        return None

    return DetectedBounds(
        min_lat=min(latitudes), min_lon=min(longitudes),
        max_lat=max(latitudes), max_lon=max(longitudes),
        source="node_extent",
    )


def _build_profile_snippet(path: str, bounds: DetectedBounds) -> str:
    file_stem = path.rsplit(".", 1)[0]
    return f'''    "given_map": MapProfile(
        name="given_map",
        bbox=BoundingBox(
            south_west_lat={bounds.min_lat}, south_west_lon={bounds.min_lon},
            north_east_lat={bounds.max_lat}, north_east_lon={bounds.max_lon},
        ),
        osm_path="{path}",
        xodr_path="{file_stem}_map.xodr",
    ),'''


def inspect_osm_file(path: str) -> None:
    with open(path, "r", encoding="utf-8", errors="replace") as osm_file:
        content = osm_file.read()

    print(f"\n{path}")
    print(
        f"nodes: {content.count('<node ')}  "
        f"ways: {content.count('<way ')}  "
        f"relations: {content.count('<relation ')} "
    )

    bounds = _bounds_from_tag(content)
    if bounds is not None:
        print("<bounds> tag found (the exact area that was originally requested): ")
    else:
        bounds = _bounds_from_node_extent(content)
        if bounds is None:
            print("No nodes found, Is this a valid .osm file? ")
            return
        print("No <bounds> tag, computed from node extent instead ")
        print("(may run slightly larger than the intended area; roads ")
        print("crossing the edge pull in nodes beyond it): ")

    print(f"\nSouth-West: {bounds.min_lat}, {bounds.min_lon} ")
    print(f"North-East: {bounds.max_lat}, {bounds.max_lon} ")
    print("\nPaste into map_profile.py:\n ")
    print(_build_profile_snippet(path, bounds))
    print('\n(Replace "given_map" in both the dict key and name= above with a real identifier.)')


if __name__ == "__main__":
    inspect_osm_file(sys.argv[1])