"""Console reporting for a UC-02 simulation result."""

from __future__ import annotations

import sys
from typing import TextIO

from .service import ScenarioSimulationReport


class ScenarioDeltaReporter:
    """Print the baseline-vs-scenario KPI delta, styled like UC-01's dashboard."""

    def __init__(self, *, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    def report(self, result: ScenarioSimulationReport) -> None:
        write = self._stream.write
        write("\n" + "=" * 70 + "\n")
        write(f"MOTION UC-02 | SCENARIO {result.scenario_id} DELTA REPORT\n")
        write(f"Ticks simulated: {result.ticks_run}\n")
        write("-" * 70 + "\n")
        write(f"{'Metric':<25}{'Baseline':>15}{'Scenario':>15}{'Delta':>15}\n")
        write(
            f"{'Corridor travel time (s)':<25}"
            f"{result.baseline.corridor_travel_time_seconds:>15.1f}"
            f"{result.scenario.corridor_travel_time_seconds:>15.1f}"
            f"{result.delta.travel_time_seconds:>+15.1f}\n"
        )
        write(
            f"{'Density (veh/km)':<25}"
            f"{result.baseline.average_density_vehicles_per_km:>15.2f}"
            f"{result.scenario.average_density_vehicles_per_km:>15.2f}"
            f"{result.delta.density_vehicles_per_km:>+15.2f}\n"
        )
        write(
            f"{'CO2 (g)':<25}"
            f"{result.baseline.total_co2_grams:>15.0f}"
            f"{result.scenario.total_co2_grams:>15.0f}"
            f"{result.delta.co2_grams:>+15.0f}\n"
        )
        write("=" * 70 + "\n\n")
