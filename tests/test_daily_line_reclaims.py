import unittest
import sys
import types
from unittest.mock import patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

# The pure signal tests do not perform downloads; avoid requiring the optional
# network client in the local test runtime.
sys.modules.setdefault("yfinance", types.ModuleType("yfinance"))

from sequential import (
    TIMEFRAMES,
    US_SESSION,
    WEEKLY_RECLAIM_TIMEFRAME,
    daily_line_reclaim_event,
    is_current_period_bar,
    period_line_reclaim_events,
    weekly_bar_is_confirmed,
)


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

    def test_opening_reclaim_uses_current_bar_orange_line(self) -> None:
        frame = base_frame()
        # The previous black candle genuinely breaks the orange line at 100.
        frame.iloc[-2, frame.columns.get_loc("Open")] = 104.0
        frame.iloc[-2, frame.columns.get_loc("Close")] = 99.0
        # Today's open is above yesterday's orange (100).  The current
        # intraday line later moves lower, but its line value at the opening
        # was 105.  This must not become an opening reclaim retroactively.
        frame.iloc[-1, frame.columns.get_loc("Open")] = 101.0
        frame.iloc[-1, frame.columns.get_loc("Close")] = 98.0

        features = pd.DataFrame(
            {
                "white_kernel": 95.0,
                "orange_upper": 100.0,
            },
            index=frame.index,
        )
        features.iloc[-1, features.columns.get_loc("orange_upper")] = 99.0
        opening_features = features.copy()
        opening_features.iloc[-1, opening_features.columns.get_loc("orange_upper")] = 105.0

        with patch(
            "sequential.ai_momentum_features",
            side_effect=[features, opening_features],
        ):
            event = daily_line_reclaim_event(frame)

        self.assertIsNone(event)

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

    def test_first_reclaim_can_happen_later_and_open_below_line(self) -> None:
        frame = base_frame()
        # Three sessions ago: black real body breaks the white line.
        frame.iloc[-3, frame.columns.get_loc("Open")] = 100.6
        frame.iloc[-3, frame.columns.get_loc("Close")] = 99.0
        # The following session stays below and does not reclaim.
        frame.iloc[-2, frame.columns.get_loc("Open")] = 99.3
        frame.iloc[-2, frame.columns.get_loc("High")] = 99.6
        frame.iloc[-2, frame.columns.get_loc("Low")] = 98.8
        frame.iloc[-2, frame.columns.get_loc("Close")] = 99.1
        # Current session opens below, then its red real body crosses back up.
        frame.iloc[-1, frame.columns.get_loc("Open")] = 99.4
        frame.iloc[-1, frame.columns.get_loc("High")] = 101.0
        frame.iloc[-1, frame.columns.get_loc("Low")] = 99.2
        frame.iloc[-1, frame.columns.get_loc("Close")] = 100.8

        event = daily_line_reclaim_event(frame)

        self.assertIsNotNone(event)
        self.assertEqual(event["opening_reclaim_lines"], [])
        self.assertEqual(event["first_reclaim_lines"], ["白線"])
        self.assertEqual(event["first_reclaim_break_bars_ago"], {"白線": 2})

    def test_live_current_body_reclaim_is_not_confirmed(self) -> None:
        frame = base_frame()
        # A confirmed white-line body break remains pending from two sessions ago.
        frame.iloc[-3, frame.columns.get_loc("Open")] = 100.6
        frame.iloc[-3, frame.columns.get_loc("Close")] = 99.0
        frame.iloc[-2, frame.columns.get_loc("Open")] = 99.3
        frame.iloc[-2, frame.columns.get_loc("Close")] = 99.1
        # The current daily bar is temporarily a valid reclaim, but its market
        # is still open.  The right-side confirmed list must not receive it.
        frame.iloc[-1, frame.columns.get_loc("Open")] = 99.4
        frame.iloc[-1, frame.columns.get_loc("Close")] = 100.8

        event = daily_line_reclaim_event(frame, allow_current_body_reclaim=False)

        self.assertIsNone(event)

    def test_opening_reclaim_keeps_an_earlier_unreclaimed_body_break(self) -> None:
        frame = base_frame()
        # A white-line body break occurs two completed sessions ago.
        frame.iloc[-3, frame.columns.get_loc("Open")] = 100.6
        frame.iloc[-3, frame.columns.get_loc("Close")] = 99.0
        # It remains below the line on the following session, so the break is
        # still pending rather than being discarded after one day.
        frame.iloc[-2, frame.columns.get_loc("Open")] = 99.3
        frame.iloc[-2, frame.columns.get_loc("Close")] = 99.1
        # Today's open jumps back above yesterday's white line.
        frame.iloc[-1, frame.columns.get_loc("Open")] = 100.7
        frame.iloc[-1, frame.columns.get_loc("High")] = 101.0
        frame.iloc[-1, frame.columns.get_loc("Low")] = 100.5
        frame.iloc[-1, frame.columns.get_loc("Close")] = 100.9

        event = daily_line_reclaim_event(frame)

        self.assertIsNotNone(event)
        self.assertEqual(event["opening_reclaim_lines"], ["白線"])

    def test_first_reclaim_is_not_repeated_on_later_bars(self) -> None:
        frame = base_frame()
        frame.iloc[-4, frame.columns.get_loc("Open")] = 100.6
        frame.iloc[-4, frame.columns.get_loc("Close")] = 99.0
        frame.iloc[-3, frame.columns.get_loc("Open")] = 99.3
        frame.iloc[-3, frame.columns.get_loc("Close")] = 99.1
        # This bar is the first reclaim and clears the pending breakdown.
        frame.iloc[-2, frame.columns.get_loc("Open")] = 99.4
        frame.iloc[-2, frame.columns.get_loc("Close")] = 100.8
        # Still above today, but it must not be labelled again.
        frame.iloc[-1, frame.columns.get_loc("Open")] = 100.7
        frame.iloc[-1, frame.columns.get_loc("Close")] = 100.9

        self.assertIsNone(daily_line_reclaim_event(frame))

    def test_weekly_bar_stays_current_through_the_same_iso_week(self) -> None:
        now = datetime(2026, 9, 1, 13, 0, tzinfo=ZoneInfo("America/New_York"))

        self.assertTrue(
            is_current_period_bar(
                pd.Timestamp("2026-08-31"), WEEKLY_RECLAIM_TIMEFRAME, US_SESSION, now
            )
        )
        self.assertFalse(
            is_current_period_bar(
                pd.Timestamp("2026-08-24"), WEEKLY_RECLAIM_TIMEFRAME, US_SESSION, now
            )
        )

    def test_weekly_body_reclaim_waits_for_friday_close(self) -> None:
        timezone = ZoneInfo("America/New_York")

        self.assertFalse(
            weekly_bar_is_confirmed(
                US_SESSION,
                datetime(2026, 9, 4, 15, 59, tzinfo=timezone),
            )
        )
        self.assertTrue(
            weekly_bar_is_confirmed(
                US_SESSION,
                datetime(2026, 9, 4, 16, 0, tzinfo=timezone),
            )
        )

    def test_weekly_keeps_previous_confirmed_reclaim_during_live_week(self) -> None:
        frame = base_frame()
        frame.index = pd.date_range("2024-10-07", periods=len(frame), freq="W-MON")
        frame.iloc[-3, frame.columns.get_loc("Open")] = 100.6
        frame.iloc[-3, frame.columns.get_loc("Close")] = 99.0
        frame.iloc[-2, frame.columns.get_loc("Open")] = 99.4
        frame.iloc[-2, frame.columns.get_loc("Close")] = 100.8
        latest_monday = frame.index[-1].date()
        now = datetime.combine(
            latest_monday + timedelta(days=1),
            datetime.min.time().replace(hour=13),
            tzinfo=ZoneInfo("America/New_York"),
        )

        events = period_line_reclaim_events(
            frame,
            WEEKLY_RECLAIM_TIMEFRAME,
            US_SESSION,
            now,
        )
        confirmed = [event for event in events if event["first_reclaim_confirmed"]]

        self.assertEqual(len(confirmed), 1)
        self.assertEqual(
            confirmed[0]["event"]["bar_index_value"],
            frame.index[-2],
        )
        self.assertEqual(confirmed[0]["event"]["first_reclaim_lines"], ["白線"])
        self.assertEqual(confirmed[0]["event"]["opening_reclaim_lines"], [])

    def test_daily_keeps_previous_confirmed_reclaim_during_live_session(self) -> None:
        frame = base_frame()
        frame.iloc[-3, frame.columns.get_loc("Open")] = 100.6
        frame.iloc[-3, frame.columns.get_loc("Close")] = 99.0
        frame.iloc[-2, frame.columns.get_loc("Open")] = 99.4
        frame.iloc[-2, frame.columns.get_loc("Close")] = 100.8
        latest_date = frame.index[-1].date()
        now = datetime.combine(
            latest_date,
            datetime.min.time().replace(hour=13),
            tzinfo=ZoneInfo("America/New_York"),
        )
        daily = next(item for item in TIMEFRAMES if item.key == "1d")

        events = period_line_reclaim_events(frame, daily, US_SESSION, now)
        confirmed = [event for event in events if event["first_reclaim_confirmed"]]

        self.assertEqual(len(confirmed), 1)
        self.assertEqual(
            confirmed[0]["event"]["bar_index_value"],
            frame.index[-2],
        )
        self.assertEqual(confirmed[0]["event"]["first_reclaim_lines"], ["白線"])


if __name__ == "__main__":
    unittest.main()
