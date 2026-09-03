from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PINE_FILE = ROOT / "tradingview" / "KJ_Big_Black_White_Golden_Screener.pine"


class BigBlackPineTests(unittest.TestCase):
    def test_complete_pine_screener_contains_required_rules(self) -> None:
        source = PINE_FILE.read_text(encoding="utf-8")

        self.assertIn("//@version=6", source)
        self.assertIn("ta.crossover(whiteLine, yellowLine)", source)
        self.assertIn("goldenCrossAge < goldenWindowBars", source)
        self.assertIn("bodyDropPct >= bodyMinPct", source)
        self.assertIn("lowerWickRangePct < lowerWickMaxPct", source)
        self.assertIn("bodyBreaksWhite or closeNearWhite", source)
        self.assertIn('plot(candidateValue, "KJ 大黑K近3根"', source)
        self.assertIn('plot(goldenCandidateValue, "KJ 金叉後低於50根"', source)
        self.assertIn("display.pine_screener", source)
        self.assertEqual(source.count("alertcondition("), 2)

    def test_screener_code_avoids_multiline_function_calls(self) -> None:
        source = PINE_FILE.read_text(encoding="utf-8")

        for line in source.splitlines():
            if not line.strip() or line.lstrip().startswith("//"):
                continue
            self.assertFalse(line.rstrip().endswith("("), line)


if __name__ == "__main__":
    unittest.main()
