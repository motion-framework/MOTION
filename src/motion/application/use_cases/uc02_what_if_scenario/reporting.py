"""Console reporting for a UC-02 simulation result."""

from __future__ import annotations

import sys
from typing import TextIO

from .service import ScenarioSimulationReport


class ScenarioDeltaReporter:
    """Print the baseline-vs-scenario KPI delta, styled like UC-01's dashboard."""

    def __init__(self, *, stream: TextIO = sys.stdout) -> None:
        self._stream = stream

    def report(self, result: ScenarioSimulationReport) -> None:
        write = self._stream.write
        write("\n" + "=" * 60 + "\n")
        write(f"MOTION UC-02 | SCENARIO {result.scenario_id} DELTA REPORT\n")
        write(f"Ticks simulated: {result.ticks_run}\n")
        write("-" * 60 + "\n")
        write(f"{'Metric':<28}{'Baseline':>12}{'Scenario':>12}{'Delta':>8}\n")
        write(
            f"{'Travel time (s)':<28}"
            f"{result.baseline.average_travel_time_seconds:>12.1f}"
            f"{result.scenario.average_travel_time_seconds:>12.1f}"
            f"{result.delta.travel_time_seconds:>+8.1f}\n"
        )
        write(
            f"{'Density (veh/km)':<28}"
            f"{result.baseline.average_density_vehicles_per_km:>12.2f}"
            f"{result.scenario.average_density_vehicles_per_km:>12.2f}"
            f"{result.delta.density_vehicles_per_km:>+8.2f}\n"
        )
        write(
            f"{'CO2 (g)':<28}"
            f"{result.baseline.total_co2_grams:>12.0f}"
            f"{result.scenario.total_co2_grams:>12.0f}"
            f"{result.delta.co2_grams:>+8.0f}\n"
        )
        write("=" * 60 + "\n\n")
