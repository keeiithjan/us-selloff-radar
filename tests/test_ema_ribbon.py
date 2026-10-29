from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from ema_ribbon import EmaRibbonSettings, ema_ribbon_signal
from sequential import (
    EMA_RIBBON_TIMEFRAME,
    TW_SESSION,
    confirmed_bars,
    ema_ribbon_export_symbols,
    resample_to_30_minutes,
)


def ohlc_frame(closes: list[float], frequency: str = "30min") -> pd.DataFrame:
    index = pd.date_range("2026-01-02 09:00", periods=len(closes), freq=frequency)
    frame = pd.DataFrame(index=index, data={"Close": closes})
    frame["Open"] = frame["Close"].shift(1).fillna(frame["Close"])
    frame["High"] = frame[["Open", "Close"]].max(axis=1) + 0.5
    frame["Low"] = frame[["Open", "Close"]].min(axis=1) - 0.5
    frame["Volume"] = 1000.0
    return frame


def five_line_reclaim_frame(*, no_break: bool = False, earlier_reclaim: bool = False) -> pd.DataFrame:
    closes = [100.0] * 237
    closes.extend([100.0, 100.0] if no_break else [97.0, 98.0])
    closes.append(102.0)
    if earlier_reclaim:
        closes[-2] = 102.0
        closes[-1] = 103.0
    return ohlc_frame(closes)


class EmaRibbonSignalTests(unittest.TestCase):
    def test_accepts_compression_break_and_first_close_above_all_five(self) -> None:
        signal = ema_ribbon_signal(five_line_reclaim_frame())

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal["stage"], "five_line_reclaim")
        self.assertLessEqual(int(signal["compression_bars_ago"]), 20)
        self.assertGreater(int(signal["break_bars_ago"]), 0)
        self.assertLessEqual(int(signal["break_bars_ago"]), 20)
        self.assertGreater(float(signal["reclaim_margin_pct"]), 0)
        self.assertLessEqual(float(signal["compression_pct"]), 3.0)

    def test_rejects_reclaim_without_a_close_below_all_five(self) -> None:
        self.assertIsNone(ema_ribbon_signal(five_line_reclaim_frame(no_break=True)))

    def test_rejects_when_an_earlier_bar_already_reclaimed_all_five(self) -> None:
        self.assertIsNone(ema_ribbon_signal(five_line_reclaim_frame(earlier_reclaim=True)))

    def test_rejects_compression_older_than_twenty_bars(self) -> None:
        closes = [100.0] * 218
        closes.extend(100.0 + step * 0.7 for step in range(1, 20))
        closes.extend([90.0, 91.0, 115.0])
        settings = EmaRibbonSettings(compression_threshold_pct=0.000001)

        self.assertIsNone(ema_ribbon_signal(ohlc_frame(closes), settings))

    def test_resamples_two_fifteen_minute_bars_into_one_thirty_minute_bar(self) -> None:
        source = ohlc_frame([100, 101, 102, 103, 104, 105, 106, 107], "15min")

        result = resample_to_30_minutes(source)

        self.assertEqual(len(result), 4)
        self.assertEqual(float(result.iloc[0]["Open"]), float(source.iloc[0]["Open"]))
        self.assertEqual(float(result.iloc[0]["Close"]), float(source.iloc[1]["Close"]))
        self.assertEqual(float(result.iloc[0]["High"]), float(source.iloc[:2]["High"].max()))
        self.assertEqual(float(result.iloc[0]["Volume"]), 2000.0)

    def test_excludes_a_still_forming_thirty_minute_bar(self) -> None:
        source = ohlc_frame([100, 101, 102], "15min")
        source.index = source.index.tz_localize(ZoneInfo("Asia/Taipei"))
        resampled = resample_to_30_minutes(source)

        result = confirmed_bars(
            resampled,
            EMA_RIBBON_TIMEFRAME,
            TW_SESSION,
            datetime(2026, 1, 2, 9, 44, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        self.assertEqual(len(resampled), 2)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.index[0].hour, 9)
        self.assertEqual(result.index[0].minute, 0)

    def test_export_keeps_only_thirty_minute_five_line_reclaims(self) -> None:
        frames = [
            {
                "key": "15m",
                "ema_ribbon_expansion": {
                    "signals": [
                        {
                            "tradingview_symbol": "NASDAQ:OLD",
                            "stage": "open_reclaim",
                            "market": "美股",
                        },
                        {
                            "tradingview_symbol": "TWSE:2330",
                            "stage": "five_line_reclaim",
                            "compression_bars_ago": 4,
                            "break_bars_ago": 1,
                            "reclaim_margin_pct": 0.8,
                            "market": "台股",
                        },
                    ]
                },
            },
            {
                "key": "1d",
                "ema_ribbon_expansion": {
                    "signals": [
                        {
                            "tradingview_symbol": "NASDAQ:DAILY",
                            "stage": "five_line_reclaim",
                            "market": "美股",
                        }
                    ]
                },
            },
        ]

        self.assertEqual(ema_ribbon_export_symbols(frames), ["TWSE:2330"])


if __name__ == "__main__":
    unittest.main()
