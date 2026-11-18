"""Console reporting for a UC-03 simulation result."""

from __future__ import annotations

import sys
from typing import TextIO

from .service import InfrastructureSimulationReport


class InfrastructureReportPrinter:
    """Print corridor KPI delta, area CO2 delta and the heatmap image path."""

    def __init__(self, *, stream: TextIO = sys.stdout) -> None:
        self._stream = stream

    def report(self, result: InfrastructureSimulationReport) -> None:
        write = self._stream.write
        write("\n" + "=" * 60 + "\n")
        write(f"MOTION UC-03 | SCENARIO {result.scenario_id} REPORT\n")
        write(f"Ticks simulated: {result.ticks_run}\n")
        write("-" * 60 + "\n")
        write(
            f"Corridor travel time : {result.baseline.corridor_travel_time_seconds:.1f}s -> "
            f"{result.scenario.corridor_travel_time_seconds:.1f}s "
            f"({result.delta.travel_time_seconds:+.1f}s)\n"
        )
        write(
            f"Corridor density     : {result.baseline.average_density_vehicles_per_km:.2f} -> "
            f"{result.scenario.average_density_vehicles_per_km:.2f} veh/km "
            f"({result.delta.density_vehicles_per_km:+.2f})\n"
        )
        write(
            f"Area CO2 estimate    : {result.baseline.total_co2_grams:.0f}g -> "
            f"{result.scenario.total_co2_grams:.0f}g "
            f"({result.delta.co2_grams:+.0f}g)\n"
        )
        write(f"Congestion heatmap   : {len(result.heatmap.cells)} segment(s), ")
        write(f"image at {result.heatmap_image_path}\n")
        write("=" * 60 + "\n\n")
