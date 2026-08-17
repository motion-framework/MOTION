from __future__ import annotations

import importlib

import pytest

from motion.domain.heatmap import CongestionCell, CongestionHeatmap
from motion.infrastructure.reporting.heatmap import (
    HeatmapRenderingError,
    render_congestion_heatmap,
)


def _heatmap() -> CongestionHeatmap:
    return CongestionHeatmap(
        cells=(
            CongestionCell("A", ((40.0, 14.0), (40.001, 14.001)), 2.0, 6.0),
            CongestionCell("B", ((40.002, 14.002),), 8.0, 1.0),
        )
    )


def test_render_congestion_heatmap_writes_a_png(tmp_path) -> None:
    pytest.importorskip("matplotlib", reason="requires the optional 'viz' extra")
    output_path = tmp_path / "heatmap.png"

    result = render_congestion_heatmap(_heatmap(), output_path, title="Test heatmap")

    assert result == output_path
    assert output_path.is_file()
    assert output_path.stat().st_size > 0
    assert not output_path.with_name(f".{output_path.name}.tmp").exists()


def test_render_congestion_heatmap_rejects_an_empty_heatmap(tmp_path) -> None:
    with pytest.raises(HeatmapRenderingError, match="no congestion cells"):
        render_congestion_heatmap(CongestionHeatmap(cells=()), tmp_path / "empty.png", title="x")


def test_render_congestion_heatmap_reports_missing_matplotlib(monkeypatch, tmp_path) -> None:
    real_import = importlib.import_module

    def guarded_import(name, package=None):
        if name.startswith("matplotlib"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", guarded_import)

    with pytest.raises(HeatmapRenderingError, match="viz"):
        render_congestion_heatmap(_heatmap(), tmp_path / "x.png", title="x")
