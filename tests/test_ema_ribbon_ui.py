from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EmaRibbonUiContractTests(unittest.TestCase):
    def test_panel_renderer_export_and_cache_version_are_wired(self) -> None:
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
        service_worker = (ROOT / "sw.js").read_text(encoding="utf-8")

        self.assertIn('id="ema-ribbon-signals"', index_html)
        self.assertNotIn('data-ema-stage=', index_html)
        self.assertNotIn("expansion_watch", index_html)
        self.assertIn("data/KJ-EMA-Ribbon-Expansion.TXT", index_html)
        self.assertIn("function renderEmaRibbon(payload)", app_js)
        self.assertIn("renderEmaRibbon(payload);", app_js)
        self.assertIn("signal.alignment_streak", app_js)
        self.assertIn("signal.compression_bars_ago", app_js)
        self.assertIn("實際連續", app_js)
        self.assertIn("距交纏", app_js)
        self.assertIn(".ema-ribbon-card.is-priority", styles)
        self.assertIn("kj-radar-shell-v31", service_worker)
        self.assertIn("20261028-ema-reclaim2", index_html)
        self.assertIn("20261028-ema-reclaim2", service_worker)


if __name__ == "__main__":
    unittest.main()

