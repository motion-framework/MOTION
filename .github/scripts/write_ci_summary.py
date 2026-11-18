"""Render MOTION CI evidence."""

from __future__ import annotations

import os
import tomllib
from argparse import ArgumentParser
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree


def _suite_totals(root: ElementTree.Element) -> dict[str, int | float]:
    suites = [root] if root.tag == "testsuite" else list(root.findall("./testsuite"))
    return {
        "tests": sum(int(suite.get("tests", "0")) for suite in suites),
        "failures": sum(int(suite.get("failures", "0")) for suite in suites),
        "errors": sum(int(suite.get("errors", "0")) for suite in suites),
        "skipped": sum(int(suite.get("skipped", "0")) for suite in suites),
        "seconds": sum(float(suite.get("time", "0")) for suite in suites),
    }


def _test_groups(root: ElementTree.Element) -> dict[str, dict[str, int]]:
    groups: dict[str, dict[str, int]] = defaultdict(
        lambda: {"passed": 0, "failed": 0, "skipped": 0}
    )
    for case in root.iter("testcase"):
        parts = case.get("classname", "other").split(".")
        key = parts[1] if len(parts) > 1 and parts[0] == "tests" else parts[0]
        group = key.replace("_", " ").title()
        if case.find("skipped") is not None:
            outcome = "skipped"
        elif case.find("failure") is not None or case.find("error") is not None:
            outcome = "failed"
        else:
            outcome = "passed"
        groups[group][outcome] += 1
    return dict(sorted(groups.items()))


def _coverage_metrics(root: ElementTree.Element) -> dict[str, float | int]:
    lines_valid = int(root.get("lines-valid", "0"))
    lines_covered = int(root.get("lines-covered", "0"))
    branches_valid = int(root.get("branches-valid", "0"))
    branches_covered = int(root.get("branches-covered", "0"))
    total_valid = lines_valid + branches_valid
    total_covered = lines_covered + branches_covered
    return {
        "combined": 100.0 * total_covered / total_valid if total_valid else 0.0,
        "lines": 100.0 * lines_covered / lines_valid if lines_valid else 0.0,
        "branches": 100.0 * branches_covered / branches_valid if branches_valid else 0.0,
        "lines_covered": lines_covered,
        "lines_valid": lines_valid,
        "branches_covered": branches_covered,
        "branches_valid": branches_valid,
    }


def _format_size(size: int) -> str:
    return f"{size / 1024:.1f} KiB" if size >= 1024 else f"{size} B"


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--junit", type=Path, default=Path("reports/junit.xml"))
    parser.add_argument("--coverage", type=Path, default=Path("reports/coverage.xml"))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--status", default=os.environ.get("JOB_STATUS", "unknown"))
    args = parser.parse_args()

    output = args.output
    if output is None:
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if not summary_path:
            parser.error("--output or GITHUB_STEP_SUMMARY is required")
        output = Path(summary_path)

    status = str(args.status).lower()
    status_text = {
        "success": "Passed",
        "failure": "Failed",
        "cancelled": "Cancelled",
    }.get(status, status.title())
    status_icon = "✅" if status == "success" else "❌"
    lines = ["## MOTION native quality gate", "", f"**Result:** {status_icon} {status_text}", ""]

    if args.junit.is_file():
        junit_root = ElementTree.parse(args.junit).getroot()
        totals = _suite_totals(junit_root)
        passed = (
            int(totals["tests"])
            - int(totals["failures"])
            - int(totals["errors"])
            - int(totals["skipped"])
        )
        lines.extend(
            [
                "### Tests",
                "",
                "| Total | Passed | Failed | Errors | Skipped | Duration |",
                "|---:|---:|---:|---:|---:|---:|",
                f"| {totals['tests']} | {passed} | {totals['failures']} | "
                f"{totals['errors']} | {totals['skipped']} | {totals['seconds']:.2f} s |",
                "",
                "| Category | Passed | Failed | Skipped |",
                "|---|---:|---:|---:|",
            ]
        )
        for group, counts in _test_groups(junit_root).items():
            lines.append(
                f"| {group} | {counts['passed']} | {counts['failed']} | {counts['skipped']} |"
            )
        lines.append("")
    else:
        lines.extend(["### Tests", "", "JUnit results were not produced.", ""])

    if args.coverage.is_file():
        coverage = _coverage_metrics(ElementTree.parse(args.coverage).getroot())
        config = tomllib.loads(args.pyproject.read_text(encoding="utf-8"))
        threshold = config["tool"]["coverage"]["report"]["fail_under"]
        lines.extend(
            [
                "### Coverage",
                "",
                "| Metric | Covered |",
                "|---|---:|",
                f"| Combined | **{coverage['combined']:.2f}%** (minimum {threshold}%) |",
                f"| Statements | {coverage['lines']:.2f}% "
                f"({coverage['lines_covered']}/{coverage['lines_valid']}) |",
                f"| Branches | {coverage['branches']:.2f}% "
                f"({coverage['branches_covered']}/{coverage['branches_valid']}) |",
                "",
            ]
        )
    else:
        lines.extend(["### Coverage", "", "Coverage results were not produced.", ""])

    distributions = sorted(path for path in args.dist.glob("*") if path.is_file())
    lines.extend(["### Python distributions", ""])
    if distributions:
        lines.extend(["| File | Size |", "|---|---:|"])
        lines.extend(
            f"| `{path.name}` | {_format_size(path.stat().st_size)} |" for path in distributions
        )
    else:
        lines.append("No distribution was produced.")
    lines.extend(["", "Detailed reports and packages are available in the run artifacts.", ""])

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines))


if __name__ == "__main__":
    main()
