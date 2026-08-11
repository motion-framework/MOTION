import re
import shutil
import sys

from typing import Optional


TAG_WITH_EDITABLE_ATTRIBUTES_PATTERN = re.compile(r'(<(?:road|object)\b)([^>]*)(>)')
ATTRIBUTE_PATTERN = re.compile(r'(\w+)="([^"]*)"')
ROAD_CLOSING_TAG_PATTERN = re.compile(r'</road>')
CLAMP_INSET_METERS = 0.01
BACKUP_SUFFIX = ".preclamp.bak"


class _RoadLengthClamper:
    def __init__(self) -> None:
        self.current_road_length: Optional[float] = None
        self.objects_patched: int = 0

    def forget_current_road(self) -> None:
        self.current_road_length = None

    def __call__(self, match: re.Match) -> str:
        tag_open, attribute_text, tag_close = match.groups()
        attributes = dict(ATTRIBUTE_PATTERN.findall(attribute_text))
        is_road_tag = tag_open.startswith("<road")

        if is_road_tag and "length" in attributes:
            self.current_road_length = float(attributes["length"])
            return match.group(0)

        is_overflowing_object = (
            not is_road_tag
            and "s" in attributes
            and self.current_road_length is not None
            and float(attributes["s"]) > self.current_road_length
        )
        if not is_overflowing_object:
            return match.group(0)

        clamped_s = max(0.0, self.current_road_length - CLAMP_INSET_METERS)
        patched_attribute_text = re.sub(r'\bs="[^"]*"', f's="{clamped_s}"', attribute_text)
        self.objects_patched += 1
        return tag_open + patched_attribute_text + tag_close


def patch(path: str) -> None:
    backup_path = path + BACKUP_SUFFIX
    shutil.copy(path, backup_path)
    print(f"Backup saved: {backup_path}")

    clamper = _RoadLengthClamper()
    patched_lines: list[str] = []

    with open(path, "r", encoding="utf-8", errors="replace") as xodr_file:
        for line in xodr_file:
            if ROAD_CLOSING_TAG_PATTERN.search(line):
                clamper.forget_current_road()
            patched_lines.append(TAG_WITH_EDITABLE_ATTRIBUTES_PATTERN.sub(clamper, line))

    with open(path, "w", encoding="utf-8", errors="replace") as xodr_file:
        xodr_file.writelines(patched_lines)

    print(f"Patched {clamper.objects_patched} <object> element(s) with s beyond their road's length.")


if __name__ == "__main__":
    patch(sys.argv[1])