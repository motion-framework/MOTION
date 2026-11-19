"""UC-03 congestion-heatmap image rendering (optional 'viz' extra).

Kept behind a lazy import, the same pattern as CARLA in
``infrastructure/maps/converter.py``, so core package import and every
non-UC-03 test never requires matplotlib.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from motion.domain.heatmap import CONGESTION_INDEX_MAX, CongestionHeatmap

FIGURE_WIDTH_INCHES = 11.0
FIGURE_HEIGHT_INCHES = 5.0
FIGURE_DPI = 150
LINE_WIDTH = 3.0


class HeatmapRenderingError(RuntimeError):
    pass


def render_congestion_heatmap(
    heatmap: CongestionHeatmap,
    output_path: Path,
    *,
    title: str,
) -> Path:
    """Render a before/after per-segment congestion map to ``output_path``.

    This is a per-segment congestion choropleth (each real corridor segment
    drawn as a colored line), not an interpolated spatial-density raster --
    MOTION's traffic model is segment-based, not a spatial density field. See
    docs/scenario-kpis.md.
    """

    if not heatmap.cells:
        raise HeatmapRenderingError("Cannot render a heatmap with no congestion cells.")
    try:
        matplotlib_module = importlib.import_module("matplotlib")
        figure_module = importlib.import_module("matplotlib.figure")
        backend_agg_module = importlib.import_module("matplotlib.backends.backend_agg")
        colors_module = importlib.import_module("matplotlib.colors")
    except ImportError as error:
        raise HeatmapRenderingError(
            "matplotlib is required to render a congestion heatmap; install the "
            '"viz" extra: pip install --editable ".[viz]"'
        ) from error

    colormap = matplotlib_module.colormaps["RdYlGn_r"]
    normalizer = colors_module.Normalize(vmin=0.0, vmax=CONGESTION_INDEX_MAX)

    figure = figure_module.Figure(
        figsize=(FIGURE_WIDTH_INCHES, FIGURE_HEIGHT_INCHES), dpi=FIGURE_DPI
    )
    canvas = backend_agg_module.FigureCanvasAgg(figure)
    before_axes = figure.add_subplot(1, 2, 1)
    after_axes = figure.add_subplot(1, 2, 2)
    before_axes.set_title("Before (real HERE traffic)")
    after_axes.set_title("After (policy-predicted, modified map)")

    for axes, value_of in (
        (before_axes, lambda cell: cell.before_congestion_index),
        (after_axes, lambda cell: cell.after_congestion_index),
    ):
        for cell in heatmap.cells:
            longitudes = [longitude for _latitude, longitude in cell.points]
            latitudes = [latitude for latitude, _longitude in cell.points]
            axes.plot(
                longitudes,
                latitudes,
                marker="o",
                linewidth=LINE_WIDTH,
                color=colormap(normalizer(value_of(cell))),
            )
        axes.set_xlabel("Longitude")
        axes.set_ylabel("Latitude")

    figure.suptitle(title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # matplotlib infers the output format from the filename suffix, so the
    # temporary file keeps the real extension and gets a distinguishing
    # prefix instead of an appended ".tmp" (which would make it e.g.
    # "heatmap.png.tmp" -- an unrecognized format).
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    canvas.print_figure(temporary_path, format=output_path.suffix.lstrip("."))
    os.replace(temporary_path, output_path)
    return output_path
