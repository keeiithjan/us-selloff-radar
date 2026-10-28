from __future__ import annotations

import unittest

import pandas as pd

from ema_ribbon import EmaRibbonSettings, ema_ribbon_features, ema_ribbon_signal
from sequential import ema_ribbon_export_symbols


def reclaim_frame(
    *,
    opening_reclaim: bool = True,
    trend_bars: int = 12,
    daily_step: float = 0.2,
) -> pd.DataFrame:
    index = pd.bdate_range("2025-01-02", periods=260)
    closes = [100.0] * (260 - trend_bars)
    closes.extend(100.0 + daily_step * step for step in range(1, trend_bars + 1))
    frame = pd.DataFrame(index=index, data={"Close": closes})
    frame["Open"] = frame["Close"].shift(1).fillna(frame["Close"])
    frame["High"] = frame[["Open", "Close"]].max(axis=1) * 1.01
    frame["Low"] = frame[["Open", "Close"]].min(axis=1) * 0.99

    if opening_reclaim:
        preliminary = ema_ribbon_features(frame)
        prior_ema9 = float(preliminary["ema9"].iloc[-3])
        frame.iloc[-2, frame.columns.get_loc("Open")] = prior_ema9 * 1.01
        frame.iloc[-2, frame.columns.get_loc("Close")] = prior_ema9 * 0.995
        frame.iloc[-2, frame.columns.get_loc("High")] = prior_ema9 * 1.015
        frame.iloc[-2, frame.columns.get_loc("Low")] = prior_ema9 * 0.99
        # Recompute the previous EMA9 after changing its close, then set the
        # current open from that completed value.  The current close is free to
        # move and must not influence the open-reclaim comparison.
        previous_ema9 = float(ema_ribbon_features(frame)["ema9"].iloc[-2])
        frame.iloc[-1, frame.columns.get_loc("Open")] = previous_ema9 * 1.01
        frame.iloc[-1, frame.columns.get_loc("High")] = max(
            frame["Open"].iloc[-1], frame["Close"].iloc[-1]
        ) * 1.01
        frame.iloc[-1, frame.columns.get_loc("Low")] = min(
            frame["Open"].iloc[-1], frame["Close"].iloc[-1]
        ) * 0.99
    return frame


class EmaRibbonSignalTests(unittest.TestCase):
    def test_rejects_expansion_without_fast_line_break_and_reclaim(self) -> None:
        self.assertIsNone(ema_ribbon_signal(reclaim_frame(opening_reclaim=False)))

    def test_accepts_recent_compression_body_break_and_next_open_reclaim(self) -> None:
        signal = ema_ribbon_signal(reclaim_frame())

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal["stage"], "open_reclaim")
        self.assertIn(9, signal["fast_break_lines"])
        self.assertTrue(signal["open_above_previous_ema9"])
        self.assertGreaterEqual(int(signal["alignment_streak"]), 3)
        self.assertLessEqual(int(signal["alignment_streak"]), 15)
        self.assertLessEqual(int(signal["compression_bars_ago"]), 20)
        self.assertLessEqual(float(signal["current_spread_pct"]), 6.0)

    def test_open_reclaim_uses_previous_ema9_not_current_close(self) -> None:
        frame = reclaim_frame()
        original = ema_ribbon_signal(frame)
        frame.iloc[-1, frame.columns.get_loc("Close")] *= 1.01
        changed = ema_ribbon_signal(frame)

        self.assertIsNotNone(original)
        self.assertIsNotNone(changed)
        assert original is not None and changed is not None
        self.assertEqual(original["previous_ema9"], changed["previous_ema9"])
        self.assertEqual(
            original["open_above_previous_ema9"],
            changed["open_above_previous_ema9"],
        )

    def test_rejects_ribbon_without_recent_compression(self) -> None:
        frame = reclaim_frame(trend_bars=60, daily_step=0.1)
        settings = EmaRibbonSettings(
            compression_threshold_pct=0.00001,
            maximum_alignment_bars=100,
        )
        self.assertIsNone(ema_ribbon_signal(frame, settings))

    def test_rejects_current_spread_above_six_percent(self) -> None:
        frame = reclaim_frame(trend_bars=40, daily_step=1.0)
        settings = EmaRibbonSettings(maximum_alignment_bars=60)
        self.assertIsNone(ema_ribbon_signal(frame, settings))

    def test_rejects_alignment_streak_above_fifteen_bars(self) -> None:
        self.assertIsNone(ema_ribbon_signal(reclaim_frame(trend_bars=20)))

    def test_rejects_compression_older_than_twenty_bars(self) -> None:
        frame = reclaim_frame(trend_bars=35, daily_step=0.15)
        settings = EmaRibbonSettings(
            compression_threshold_pct=0.05,
            maximum_alignment_bars=40,
        )
        self.assertIsNone(ema_ribbon_signal(frame, settings))

    def test_export_keeps_only_open_reclaims_and_removes_duplicates(self) -> None:
        frames = [
            {
                "key": "1d",
                "ema_ribbon_expansion": {
                    "signals": [
                        {
                            "tradingview_symbol": "NASDAQ:WATCH",
                            "stage": "expansion_watch",
                            "expansion_score": 80,
                            "market": "美股",
                        },
                        {
                            "tradingview_symbol": "TWSE:2330",
                            "stage": "open_reclaim",
                            "expansion_score": 55,
                            "market": "台股",
                        },
                        {
                            "tradingview_symbol": "NASDAQ:WATCH",
                            "stage": "expansion_watch",
                            "expansion_score": 80,
                            "market": "美股",
                        },
                    ]
                },
            }
        ]

        self.assertEqual(
            ema_ribbon_export_symbols(frames),
            ["TWSE:2330"],
        )


if __name__ == "__main__":
    unittest.main()

