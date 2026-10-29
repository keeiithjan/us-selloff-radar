from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EmaRibbonUiContractTests(unittest.TestCase):
    def test_panel_renderer_export_and_cache_version_are_wired(self) -> None:
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
        sequential_py = (ROOT / "sequential.py").read_text(encoding="utf-8")
        service_worker = (ROOT / "sw.js").read_text(encoding="utf-8")

        self.assertIn('id="ema-ribbon-signals"', index_html)
        self.assertNotIn('data-ema-stage=', index_html)
        self.assertNotIn("expansion_watch", index_html)
        self.assertIn("data/KJ-EMA-Ribbon-Expansion.TXT", index_html)
        self.assertIn("function renderEmaRibbon(payload)", app_js)
        self.assertIn("renderEmaRibbon(payload);", app_js)
        self.assertIn('signal.stage === "five_line_reclaim"', app_js)
        self.assertIn("signal.compression_bars_ago", app_js)
        self.assertIn("signal.break_bars_ago", app_js)
        self.assertIn("signal.reclaim_margin_pct", app_js)
        self.assertIn('makeTradingViewLink(signal, "30")', app_js)
        self.assertIn("30 分鐘", index_html)
        self.assertIn("距壓縮", app_js)
        self.assertIn("距跌破", app_js)
        self.assertIn("站回幅度", app_js)
        self.assertIn('EMA_RIBBON_TIMEFRAME = Timeframe("30m"', sequential_py)
        self.assertIn('limit = 500 if timeframe.key == "15m" else 120', sequential_py)
        self.assertIn(".ema-ribbon-card.is-priority", styles)
        self.assertIn("kj-radar-shell-v33", service_worker)
        self.assertIn("20261029-ema-30m1", index_html)
        self.assertIn("20261029-ema-30m1", service_worker)


if __name__ == "__main__":
    unittest.main()

