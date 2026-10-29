from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ModeSelectorUiContractTests(unittest.TestCase):
    def test_sticky_selector_targets_behavior_and_cache_are_wired(self) -> None:
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
        service_worker = (ROOT / "sw.js").read_text(encoding="utf-8")

        self.assertIn('id="mode-selector"', index_html)
        targets = (
            "line-reclaim-command",
            "big-black-command",
            "ema-ribbon-command",
            "market-pulse-mode",
            "weekly-reclaim-monitor",
            "td-monitor",
        )
        for target in targets:
            self.assertIn(f'value="{target}"', index_html)
            self.assertIn(f'id="{target}"', index_html)

        self.assertIn("function configureModeSelector()", app_js)
        self.assertIn("function navigateToMode(targetId)", app_js)
        self.assertIn('scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth"', app_js)
        self.assertIn(".mode-switcher", styles)
        self.assertIn("position: sticky", styles)
        self.assertIn(".mode-target", styles)
        self.assertIn("kj-radar-shell-v33", service_worker)
        self.assertIn("20261029-ema-30m1", index_html)
        self.assertIn("20261029-ema-30m1", service_worker)


if __name__ == "__main__":
    unittest.main()
