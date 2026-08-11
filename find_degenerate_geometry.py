import re
import sys
from dataclasses import dataclass
from typing import Optional


GEOMETRY_TAG_PATTERN = re.compile(r"<geometry\s+([^>]*?)/?>", re.IGNORECASE)
ATTRIBUTE_PATTERN = re.compile(r'(\w+)="([^"]*)"')
MAX_PROBLEMS_TO_DISPLAY = 25


@dataclass
class DegenerateGeometry:
    line_number: int
    reason: str
    s_position: Optional[str]
    x_position: Optional[str]
    y_position: Optional[str]
    heading: Optional[str]


def _classify_length(length_text: str) -> Optional[str]:
    try:
        length = float(length_text)
    except ValueError:
        return f"non-numeric length={length_text!r}"

    if not (length > 0):
        return f"length={length}"

    return None


def scan(path: str) -> int:
    total_geometries_scanned = 0
    problems: list[DegenerateGeometry] = []

    with open(path, "r", encoding="utf-8", errors="replace") as xodr_file:
        for line_number, line in enumerate(xodr_file, start=1):
            for match in GEOMETRY_TAG_PATTERN.finditer(line):
                total_geometries_scanned += 1
                attributes = dict(ATTRIBUTE_PATTERN.findall(match.group(1)))

                reason = _classify_length(attributes.get("length", ""))
                if reason is not None:
                    problems.append(DegenerateGeometry(
                        line_number=line_number,
                        reason=reason,
                        s_position=attributes.get("s"),
                        x_position=attributes.get("x"),
                        y_position=attributes.get("y"),
                        heading=attributes.get("hdg"),
                    ))

    _report(path, total_geometries_scanned, problems)
    return len(problems)


def _report(path: str, total_geometries_scanned: int, problems: list[DegenerateGeometry]) -> None:
    print(f"Scanned {total_geometries_scanned} <geometry> elements in {path} ")

    if not problems:
        print("\nNo zero-length or non-numeric <geometry> elements found. ")
        print("The problem may be elsewhere (... a lane width or junction issue) ... ")
        return

    print(f"\nFound {len(problems)} problematic geometries: ")
    for problem in problems[:MAX_PROBLEMS_TO_DISPLAY]:
        print(
            f"line {problem.line_number}: {problem.reason}  "
            f"s={problem.s_position} x={problem.x_position} "
            f"y={problem.y_position} hdg={problem.heading} "
        )


if __name__ == "__main__":
    scan(sys.argv[1])