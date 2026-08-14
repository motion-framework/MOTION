from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from motion.domain.geography import BoundingBox
from motion.domain.maps import KEPT_WAY_TYPES, MapProfile
from motion.infrastructure.maps.converter import (
    CarlaOsmToOpenDriveConverter,
    MapConversionError,
)
from motion.infrastructure.maps.geometry import (
    patch_object_overflows,
    patch_zero_length_geometries,
    scan_degenerate_geometries,
    scan_object_overflows,
)
from motion.infrastructure.maps.osm_inspection import inspect_osm
from motion.infrastructure.maps.projection import build_geo_transform

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "maps"


class FakeTransformer:
    def transform(self, longitude: float, latitude: float) -> tuple[float, float]:
        return longitude * 10, latitude * 20


class FakeOsm2OdrSettings:
    def __init__(self) -> None:
        self.way_types: list[str] = []
        self.proj_string = ""

    def set_osm_way_types(self, values: list[str]) -> None:
        self.way_types = values


class FakeOsm2Odr:
    settings: FakeOsm2OdrSettings | None = None

    @classmethod
    def convert(cls, osm_data: str, settings: FakeOsm2OdrSettings) -> str:
        assert "<osm" in osm_data
        cls.settings = settings
        return "<OpenDRIVE><header/></OpenDRIVE>"


def test_osm_inspection_and_projection_use_only_road_nodes() -> None:
    path = FIXTURES / "minimal.osm"
    inspection = inspect_osm(path)
    assert (inspection.node_count, inspection.way_count, inspection.relation_count) == (
        3,
        2,
        0,
    )
    assert inspection.bounds is not None
    assert inspection.bounds.source == "bounds_tag"

    transform = build_geo_transform(path, "+proj=fake", transformer=FakeTransformer())
    assert transform.min_easting == 140.0
    assert transform.min_northing == 800.0


def test_scanners_and_repairs_preserve_expected_narrow_scope(tmp_path) -> None:
    path = tmp_path / "map.xodr"
    shutil.copy2(FIXTURES / "defective.xodr", path)
    geometry_count, degenerate = scan_degenerate_geometries(path)
    object_count, overflow = scan_object_overflows(path)
    assert geometry_count == 2
    assert len(degenerate) == 1
    assert object_count == 1
    assert len(overflow) == 1

    assert patch_zero_length_geometries(path).patched_count == 1
    assert patch_object_overflows(path).patched_count == 1
    assert not scan_degenerate_geometries(path)[1]
    assert not scan_object_overflows(path)[1]
    assert (tmp_path / "map.xodr.prepatch.bak").exists()
    assert (tmp_path / "map.xodr.preclamp.bak").exists()


def test_carla_converter_is_lazy_and_writes_the_declared_profile(tmp_path, monkeypatch) -> None:
    osm_path = tmp_path / "map.osm"
    shutil.copy2(FIXTURES / "minimal.osm", osm_path)
    profile = MapProfile(
        name="map",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        osm_path=osm_path,
        xodr_path=tmp_path / "nested" / "map.xodr",
    )
    fake_carla = SimpleNamespace(
        Osm2OdrSettings=FakeOsm2OdrSettings,
        Osm2Odr=FakeOsm2Odr,
    )
    monkeypatch.setattr(
        "motion.infrastructure.maps.converter.importlib.import_module",
        lambda name: fake_carla if name == "carla" else None,
    )

    output = CarlaOsmToOpenDriveConverter().convert(profile)

    assert output.read_text(encoding="utf-8") == "<OpenDRIVE><header/></OpenDRIVE>"
    assert FakeOsm2Odr.settings is not None
    assert FakeOsm2Odr.settings.way_types == list(KEPT_WAY_TYPES)
    assert FakeOsm2Odr.settings.proj_string == profile.proj_string
    assert not output.with_suffix(".xodr.tmp").exists()


def test_carla_converter_reports_missing_api_without_import_side_effects(
    tmp_path, monkeypatch
) -> None:
    profile = MapProfile(
        name="missing",
        bbox=BoundingBox(40.0, 14.0, 40.01, 14.01),
        osm_path=tmp_path / "missing.osm",
        xodr_path=tmp_path / "missing.xodr",
    )

    def missing(_name: str):
        raise ImportError

    monkeypatch.setattr(
        "motion.infrastructure.maps.converter.importlib.import_module",
        missing,
    )
    with pytest.raises(MapConversionError, match="CARLA Python API"):
        CarlaOsmToOpenDriveConverter().convert(profile)
