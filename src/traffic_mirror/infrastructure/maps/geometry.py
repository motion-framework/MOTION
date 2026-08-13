"""Deterministic OpenDRIVE validation and narrowly scoped repair."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

GEOMETRY_TAG_PATTERN = re.compile(r"<geometry\s+([^>]*?)/?>", re.IGNORECASE)
ROAD_OR_OBJECT_TAG_PATTERN = re.compile(r"<(road|object)\b([^>]*)>")
ATTRIBUTE_PATTERN = re.compile(r'(\w+)="([^"]*)"')
ROAD_CLOSING_TAG_PATTERN = re.compile(r"</road>")
ZERO_LENGTH_PATTERN = re.compile(r'(<geometry\b[^>]*\blength=")0(?:\.0+)?(")')
TAG_WITH_EDITABLE_ATTRIBUTES_PATTERN = re.compile(r"(<(?:road|object)\b)([^>]*)(>)")

FLOATING_POINT_TOLERANCE_METERS = 1e-6
REPLACEMENT_LENGTH_TEXT = "0.001"
CLAMP_INSET_METERS = 0.01


@dataclass(frozen=True, slots=True)
class DegenerateGeometry:
    line_number: int
    reason: str
    s_position: str | None
    x_position: str | None
    y_position: str | None
    heading: str | None


@dataclass(frozen=True, slots=True)
class ObjectOverflow:
    line_number: int
    road_id: str | None
    object_type: str
    object_s_position: float
    road_length: float


@dataclass(frozen=True, slots=True)
class RepairResult:
    patched_count: int
    backup_path: Path | None


def classify_geometry_length(length_text: str) -> str | None:
    try:
        length = float(length_text)
    except ValueError:
        return f"non-numeric length={length_text!r}"
    if not (length > 0):
        return f"length={length}"
    return None


def scan_degenerate_geometries(path: Path) -> tuple[int, list[DegenerateGeometry]]:
    total = 0
    problems: list[DegenerateGeometry] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, start=1):
            for match in GEOMETRY_TAG_PATTERN.finditer(line):
                total += 1
                attributes = dict(ATTRIBUTE_PATTERN.findall(match.group(1)))
                reason = classify_geometry_length(attributes.get("length", ""))
                if reason is not None:
                    problems.append(
                        DegenerateGeometry(
                            line_number=line_number,
                            reason=reason,
                            s_position=attributes.get("s"),
                            x_position=attributes.get("x"),
                            y_position=attributes.get("y"),
                            heading=attributes.get("hdg"),
                        )
                    )
    return total, problems


def scan_object_overflows(path: Path) -> tuple[int, list[ObjectOverflow]]:
    current_road_id: str | None = None
    current_road_length: float | None = None
    total = 0
    violations: list[ObjectOverflow] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, start=1):
            if ROAD_CLOSING_TAG_PATTERN.search(line):
                current_road_id = None
                current_road_length = None
            for tag_name, attribute_text in ROAD_OR_OBJECT_TAG_PATTERN.findall(line):
                attributes = dict(ATTRIBUTE_PATTERN.findall(attribute_text))
                if tag_name == "road" and "length" in attributes:
                    current_road_id = attributes.get("id")
                    current_road_length = float(attributes["length"])
                elif tag_name == "object" and "s" in attributes:
                    total += 1
                    object_s = float(attributes["s"])
                    if (
                        current_road_length is not None
                        and object_s > current_road_length + FLOATING_POINT_TOLERANCE_METERS
                    ):
                        violations.append(
                            ObjectOverflow(
                                line_number=line_number,
                                road_id=current_road_id,
                                object_type=attributes.get("type", "unknown"),
                                object_s_position=object_s,
                                road_length=current_road_length,
                            )
                        )
    return total, violations


def patch_zero_length_geometries(path: Path, *, backup: bool = True) -> RepairResult:
    content = path.read_text(encoding="utf-8", errors="replace")
    patched, count = ZERO_LENGTH_PATTERN.subn(rf"\g<1>{REPLACEMENT_LENGTH_TEXT}\g<2>", content)
    backup_path = _backup(path, ".prepatch.bak") if backup and count else None
    if count:
        _atomic_write_text(path, patched)
    return RepairResult(count, backup_path)


class _RoadLengthClamper:
    def __init__(self) -> None:
        self.current_road_length: float | None = None
        self.objects_patched = 0

    def __call__(self, match: re.Match[str]) -> str:
        tag_open, attribute_text, tag_close = match.groups()
        attributes = dict(ATTRIBUTE_PATTERN.findall(attribute_text))
        is_road = tag_open.startswith("<road")
        if is_road and "length" in attributes:
            self.current_road_length = float(attributes["length"])
            return match.group(0)
        road_length = self.current_road_length
        overflowing = (
            not is_road
            and "s" in attributes
            and road_length is not None
            and float(attributes["s"]) > road_length
        )
        if not overflowing:
            return match.group(0)
        assert road_length is not None
        clamped = max(0.0, road_length - CLAMP_INSET_METERS)
        attributes_text = re.sub(r'\bs="[^"]*"', f's="{clamped}"', attribute_text)
        self.objects_patched += 1
        return tag_open + attributes_text + tag_close


def patch_object_overflows(path: Path, *, backup: bool = True) -> RepairResult:
    clamper = _RoadLengthClamper()
    output_lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if ROAD_CLOSING_TAG_PATTERN.search(line):
                clamper.current_road_length = None
            output_lines.append(TAG_WITH_EDITABLE_ATTRIBUTES_PATTERN.sub(clamper, line))
    backup_path = _backup(path, ".preclamp.bak") if backup and clamper.objects_patched else None
    if clamper.objects_patched:
        _atomic_write_text(path, "".join(output_lines))
    return RepairResult(clamper.objects_patched, backup_path)


def _backup(path: Path, suffix: str) -> Path:
    backup_path = path.with_name(path.name + suffix)
    shutil.copy2(path, backup_path)
    return backup_path


def _atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)
