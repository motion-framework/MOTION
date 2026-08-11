import re
import sys
from dataclasses import dataclass
from typing import Optional


ROAD_OR_OBJECT_TAG_PATTERN = re.compile(r'<(road|object)\b([^>]*)>')
ATTRIBUTE_PATTERN = re.compile(r'(\w+)="([^"]*)"')
ROAD_CLOSING_TAG_PATTERN = re.compile(r'</road>')
FLOATING_POINT_TOLERANCE_METERS = 1e-6
MAX_VIOLATIONS_TO_DISPLAY = 25


@dataclass
class OverflowViolation:
    line_number: int
    road_id: Optional[str]
    object_type: str
    object_s_position: float
    road_length: float

    @property
    def overflow_meters(self) -> float:
        return self.object_s_position - self.road_length


def scan(path: str) -> int:
    current_road_id: Optional[str] = None
    current_road_length: Optional[float] = None
    total_objects_scanned = 0
    violations: list[OverflowViolation] = []

    with open(path, "r", encoding="utf-8", errors="replace") as xodr_file:
        for line_number, line in enumerate(xodr_file, start=1):
            if ROAD_CLOSING_TAG_PATTERN.search(line):
                current_road_id = None
                current_road_length = None

            for tag_name, attribute_text in ROAD_OR_OBJECT_TAG_PATTERN.findall(line):
                attributes = dict(ATTRIBUTE_PATTERN.findall(attribute_text))

                if tag_name == "road" and "length" in attributes:
                    current_road_id = attributes.get("id")
                    current_road_length = float(attributes["length"])

                elif tag_name == "object" and "s" in attributes:
                    total_objects_scanned += 1
                    object_s_position = float(attributes["s"])

                    road_length_is_known = current_road_length is not None
                    exceeds_road_length = (
                        road_length_is_known
                        and object_s_position > current_road_length + FLOATING_POINT_TOLERANCE_METERS
                    )
                    if exceeds_road_length:
                        violations.append(OverflowViolation(
                            line_number=line_number,
                            road_id=current_road_id,
                            object_type=attributes.get("type", "unknown"),
                            object_s_position=object_s_position,
                            road_length=current_road_length,
                        ))

    _report(path, total_objects_scanned, violations)
    return len(violations)


def _report(path: str, total_objects_scanned: int, violations: list[OverflowViolation]) -> None:
    print(f"Scanned {total_objects_scanned} <object> elements in {path}")

    if not violations:
        print("\nNo <object> elements found exceeding their road's length. ")
        print("The crash may involve a <signal> element or a lane-section boundary ")
        return

    print(f"\nFound {len(violations)} object(s) placed beyond their road's length: ")
    for violation in violations[:MAX_VIOLATIONS_TO_DISPLAY]:
        print(
            f"line {violation.line_number}: "
            f"road id={violation.road_id} type={violation.object_type}  "
            f"s={violation.object_s_position} > length={violation.road_length}  "
            f"(overflow={violation.overflow_meters:.4f}m) "
        )


if __name__ == "__main__":
    scan(sys.argv[1])