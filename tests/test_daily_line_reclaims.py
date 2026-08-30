import unittest
import sys
import types

import pandas as pd

# The pure signal tests do not perform downloads; avoid requiring the optional
# network client in the local test runtime.
sys.modules.setdefault("yfinance", types.ModuleType("yfinance"))

from sequential import daily_line_reclaim_event


def base_frame() -> pd.DataFrame:
    index = pd.date_range("2026-04-01", periods=100, freq="D")
    return pd.DataFrame(
        {
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.0,
            "Volume": 1_000_000.0,
        },
        index=index,
    )


class DailyLineReclaimTests(unittest.TestCase):
    def test_requires_previous_real_body_break(self) -> None:
        frame = base_frame()
        frame.iloc[-1, frame.columns.get_loc("Open")] = 105.0
        frame.iloc[-1, frame.columns.get_loc("Close")] = 106.0
        self.assertIsNone(daily_line_reclaim_event(frame))

    def test_white_body_break_then_open_and_first_reclaim(self) -> None:
        frame = base_frame()
        frame.iloc[-2, frame.columns.get_loc("Open")] = 100.6
        frame.iloc[-2, frame.columns.get_loc("Close")] = 99.0
        frame.iloc[-1, frame.columns.get_loc("Open")] = 100.7
        frame.iloc[-1, frame.columns.get_loc("High")] = 101.0
        frame.iloc[-1, frame.columns.get_loc("Low")] = 100.5
        frame.iloc[-1, frame.columns.get_loc("Close")] = 100.9

        event = daily_line_reclaim_event(frame)

        self.assertIsNotNone(event)
        self.assertEqual(event["broken_lines"], ["白線"])
        self.assertEqual(event["opening_reclaim_lines"], ["白線"])
        self.assertEqual(event["first_reclaim_lines"], ["白線"])

    def test_orange_body_break_then_open_and_first_reclaim(self) -> None:
        frame = base_frame()
        frame.iloc[-2, frame.columns.get_loc("Open")] = 104.0
        frame.iloc[-2, frame.columns.get_loc("High")] = 104.5
        frame.iloc[-2, frame.columns.get_loc("Close")] = 100.5
        frame.iloc[-1, frame.columns.get_loc("Open")] = 105.0
        frame.iloc[-1, frame.columns.get_loc("High")] = 105.2
        frame.iloc[-1, frame.columns.get_loc("Low")] = 104.7
        frame.iloc[-1, frame.columns.get_loc("Close")] = 105.1

        event = daily_line_reclaim_event(frame)

        self.assertIsNotNone(event)
        self.assertIn("橙線", event["broken_lines"])
        self.assertIn("橙線", event["opening_reclaim_lines"])
        self.assertIn("橙線", event["first_reclaim_lines"])

    def test_cash_index_without_volume_is_still_scanned(self) -> None:
        frame = base_frame().drop(columns="Volume")
        frame.iloc[-2, frame.columns.get_loc("Open")] = 100.6
        frame.iloc[-2, frame.columns.get_loc("Close")] = 99.0
        frame.iloc[-1, frame.columns.get_loc("Open")] = 100.7
        frame.iloc[-1, frame.columns.get_loc("Low")] = 100.5
        frame.iloc[-1, frame.columns.get_loc("Close")] = 100.9

        event = daily_line_reclaim_event(frame)

        self.assertIsNotNone(event)
        self.assertEqual(event["opening_reclaim_lines"], ["白線"])


if __name__ == "__main__":
    unittest.main()
