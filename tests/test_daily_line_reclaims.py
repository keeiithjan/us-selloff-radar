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
    big_black_white_break_events,
    carry_forward_line_reclaim_first_shown,
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
    def test_big_black_requires_large_body_white_cross_and_small_lower_wick(self) -> None:
        frame = base_frame().iloc[:8].copy()
        signal_position = len(frame) - 1
        frame.iloc[signal_position, frame.columns.get_loc("Open")] = 106.0
        frame.iloc[signal_position, frame.columns.get_loc("High")] = 106.2
        frame.iloc[signal_position, frame.columns.get_loc("Low")] = 99.95
        frame.iloc[signal_position, frame.columns.get_loc("Close")] = 100.0
        features = pd.DataFrame({"white_kernel": 103.0}, index=frame.index)
        daily = next(item for item in TIMEFRAMES if item.key == "1d")
        now = datetime(2026, 5, 1, 18, 0, tzinfo=ZoneInfo("America/New_York"))

        with patch("sequential.ai_momentum_features", return_value=features):
            events = big_black_white_break_events(frame, daily, US_SESSION, now)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["bars_ago"], 0)
        self.assertGreaterEqual(events[0]["body_drop_pct"], 5)
        self.assertLess(events[0]["lower_wick_range_pct"], 5)

    def test_big_black_accepts_lower_wick_between_five_and_ten_percent(self) -> None:
        frame = base_frame().iloc[:8].copy()
        frame.iloc[-1, frame.columns.get_loc("Open")] = 106.0
        frame.iloc[-1, frame.columns.get_loc("High")] = 106.2
        frame.iloc[-1, frame.columns.get_loc("Low")] = 99.5
        frame.iloc[-1, frame.columns.get_loc("Close")] = 100.0
        features = pd.DataFrame({"white_kernel": 103.0}, index=frame.index)
        daily = next(item for item in TIMEFRAMES if item.key == "1d")
        now = datetime(2026, 5, 1, 18, 0, tzinfo=ZoneInfo("America/New_York"))

        with patch("sequential.ai_momentum_features", return_value=features):
            events = big_black_white_break_events(frame, daily, US_SESSION, now)

        self.assertEqual(len(events), 1)
        self.assertGreater(events[0]["lower_wick_range_pct"], 5)
        self.assertLess(events[0]["lower_wick_range_pct"], 10)

    def test_big_black_rejects_lower_wick_at_or_above_ten_percent(self) -> None:
        frame = base_frame().iloc[:8].copy()
        frame.iloc[-1, frame.columns.get_loc("Open")] = 106.0
        frame.iloc[-1, frame.columns.get_loc("High")] = 106.2
        frame.iloc[-1, frame.columns.get_loc("Low")] = 99.0
        frame.iloc[-1, frame.columns.get_loc("Close")] = 100.0
        features = pd.DataFrame({"white_kernel": 103.0}, index=frame.index)
        daily = next(item for item in TIMEFRAMES if item.key == "1d")
        now = datetime(2026, 5, 1, 18, 0, tzinfo=ZoneInfo("America/New_York"))

        with patch("sequential.ai_momentum_features", return_value=features):
            events = big_black_white_break_events(frame, daily, US_SESSION, now)

        self.assertEqual(events, [])

    def test_big_black_accepts_close_within_one_percent_above_white(self) -> None:
        frame = base_frame().iloc[:8].copy()
        frame.iloc[-1, frame.columns.get_loc("Open")] = 107.0
        frame.iloc[-1, frame.columns.get_loc("High")] = 107.2
        frame.iloc[-1, frame.columns.get_loc("Low")] = 100.95
        frame.iloc[-1, frame.columns.get_loc("Close")] = 101.0
        features = pd.DataFrame({"white_kernel": 100.5}, index=frame.index)
        daily = next(item for item in TIMEFRAMES if item.key == "1d")
        now = datetime(2026, 5, 1, 18, 0, tzinfo=ZoneInfo("America/New_York"))

        with patch("sequential.ai_momentum_features", return_value=features):
            events = big_black_white_break_events(frame, daily, US_SESSION, now)

        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["breaks_white"])
        self.assertTrue(events[0]["near_white"])
        self.assertEqual(events[0]["white_relation"], "near")
        self.assertLessEqual(abs(events[0]["white_distance_pct"]), 1)

    def test_big_black_rejects_non_break_more_than_one_percent_from_white(self) -> None:
        frame = base_frame().iloc[:8].copy()
        frame.iloc[-1, frame.columns.get_loc("Open")] = 107.0
        frame.iloc[-1, frame.columns.get_loc("High")] = 107.2
        frame.iloc[-1, frame.columns.get_loc("Low")] = 101.45
        frame.iloc[-1, frame.columns.get_loc("Close")] = 101.5
        features = pd.DataFrame({"white_kernel": 100.0}, index=frame.index)
        daily = next(item for item in TIMEFRAMES if item.key == "1d")
        now = datetime(2026, 5, 1, 18, 0, tzinfo=ZoneInfo("America/New_York"))

        with patch("sequential.ai_momentum_features", return_value=features):
            events = big_black_white_break_events(frame, daily, US_SESSION, now)

        self.assertEqual(events, [])

    def test_big_black_daily_search_is_limited_to_last_three_completed_bars(self) -> None:
        frame = base_frame().iloc[:9].copy()
        frame.iloc[-4, frame.columns.get_loc("Open")] = 106.0
        frame.iloc[-4, frame.columns.get_loc("High")] = 106.2
        frame.iloc[-4, frame.columns.get_loc("Low")] = 99.95
        frame.iloc[-4, frame.columns.get_loc("Close")] = 100.0
        features = pd.DataFrame({"white_kernel": 103.0}, index=frame.index)
        daily = next(item for item in TIMEFRAMES if item.key == "1d")
        now = datetime(2026, 5, 1, 18, 0, tzinfo=ZoneInfo("America/New_York"))

        with patch("sequential.ai_momentum_features", return_value=features):
            events = big_black_white_break_events(frame, daily, US_SESSION, now)

        self.assertEqual(events, [])

    def test_big_black_records_golden_cross_age_at_the_signal_bar(self) -> None:
        frame = base_frame().iloc[:70].copy()
        frame.iloc[-1, frame.columns.get_loc("Open")] = 106.0
        frame.iloc[-1, frame.columns.get_loc("High")] = 106.2
        frame.iloc[-1, frame.columns.get_loc("Low")] = 99.95
        frame.iloc[-1, frame.columns.get_loc("Close")] = 100.0
        cross_position = len(frame) - 1 - 49
        white = pd.Series(99.0, index=frame.index)
        yellow = pd.Series(100.0, index=frame.index)
        white.iloc[cross_position:] = 101.0
        white.iloc[-1] = 103.0
        features = pd.DataFrame(
            {"white_kernel": white, "yellow_mid": yellow},
            index=frame.index,
        )
        daily = next(item for item in TIMEFRAMES if item.key == "1d")
        now = datetime(2026, 8, 1, 18, 0, tzinfo=ZoneInfo("America/New_York"))

        with patch("sequential.ai_momentum_features", return_value=features):
            events = big_black_white_break_events(frame, daily, US_SESSION, now)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["golden_cross_age_bars"], 49)
        self.assertTrue(events[0]["golden_cross_within_50"])
        self.assertEqual(events[0]["yellow_line"], 100.0)

    def test_big_black_golden_cross_exactly_fifty_bars_ago_is_excluded(self) -> None:
        frame = base_frame().iloc[:70].copy()
        frame.iloc[-1, frame.columns.get_loc("Open")] = 106.0
        frame.iloc[-1, frame.columns.get_loc("High")] = 106.2
        frame.iloc[-1, frame.columns.get_loc("Low")] = 99.95
        frame.iloc[-1, frame.columns.get_loc("Close")] = 100.0
        cross_position = len(frame) - 1 - 50
        white = pd.Series(99.0, index=frame.index)
        yellow = pd.Series(100.0, index=frame.index)
        white.iloc[cross_position:] = 101.0
        white.iloc[-1] = 103.0
        features = pd.DataFrame(
            {"white_kernel": white, "yellow_mid": yellow},
            index=frame.index,
        )
        daily = next(item for item in TIMEFRAMES if item.key == "1d")
        now = datetime(2026, 8, 1, 18, 0, tzinfo=ZoneInfo("America/New_York"))

        with patch("sequential.ai_momentum_features", return_value=features):
            events = big_black_white_break_events(frame, daily, US_SESSION, now)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["golden_cross_age_bars"], 50)
        self.assertFalse(events[0]["golden_cross_within_50"])

    def test_big_black_weekly_excludes_the_unfinished_current_week(self) -> None:
        frame = base_frame().iloc[:8].copy()
        frame.index = pd.date_range("2026-07-13", periods=len(frame), freq="W-MON")
        for position in (-2, -1):
            frame.iloc[position, frame.columns.get_loc("Open")] = 106.0
            frame.iloc[position, frame.columns.get_loc("High")] = 106.2
            frame.iloc[position, frame.columns.get_loc("Low")] = 99.95
            frame.iloc[position, frame.columns.get_loc("Close")] = 100.0
        latest_monday = frame.index[-1].date()
        now = datetime.combine(
            latest_monday + timedelta(days=1),
            datetime.min.time().replace(hour=13),
            tzinfo=ZoneInfo("America/New_York"),
        )

        def white_features(clean: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame({"white_kernel": 103.0}, index=clean.index)

        with patch("sequential.ai_momentum_features", side_effect=white_features):
            events = big_black_white_break_events(
                frame, WEEKLY_RECLAIM_TIMEFRAME, US_SESSION, now
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["bar_index_value"], frame.index[-2])
        self.assertEqual(events[0]["bars_ago"], 0)

    def test_big_black_first_shown_time_is_persisted(self) -> None:
        prior_time = "2026-09-02T11:00:00+00:00"
        current_time = "2026-09-03T11:00:00+00:00"
        signal_id = "big-black:1d:NASDAQ:AAA:2026-09-02"
        previous = {
            "timeframes": [{
                "key": "1d",
                "daily_line_reclaims": {"signals": []},
                "big_black_body_breaks": {"signals": [{
                    "signal_id": signal_id,
                    "signal_type": "big_black_white_break",
                    "first_shown_at_utc": prior_time,
                }]},
            }],
            "weekly_reclaim": {"line_reclaims": {"signals": []}},
        }
        payload = {
            "timeframes": [{
                "key": "1d",
                "daily_line_reclaims": {"signals": []},
                "big_black_body_breaks": {"signals": [
                    {"signal_id": signal_id, "signal_type": "big_black_white_break"},
                    {"signal_id": "big-black:1d:NYSE:BBB:2026-09-03", "signal_type": "big_black_white_break"},
                ]},
            }],
            "weekly_reclaim": {"line_reclaims": {"signals": []}},
        }

        carry_forward_line_reclaim_first_shown(payload, previous, current_time)

        signals = payload["timeframes"][0]["big_black_body_breaks"]["signals"]
        self.assertEqual(signals[0]["first_shown_at_utc"], prior_time)
        self.assertEqual(signals[1]["first_shown_at_utc"], current_time)

    def test_first_shown_time_is_carried_forward_by_signal_id(self) -> None:
        prior_time = "2026-09-01T13:30:01+00:00"
        current_time = "2026-09-02T13:30:02+00:00"
        previous = {
            "timeframes": [{
                "key": "1d",
                "daily_line_reclaims": {
                    "signals": [{
                        "signal_id": "1d:NASDAQ:AAA:2026-09-01",
                        "first_shown_at_utc": prior_time,
                    }],
                },
            }],
            "weekly_reclaim": {"line_reclaims": {"signals": []}},
        }
        payload = {
            "timeframes": [{
                "key": "1d",
                "daily_line_reclaims": {
                    "signals": [
                        {
                            "signal_id": "1d:NASDAQ:AAA:2026-09-01",
                            "first_reclaim_lines": ["白線"],
                            "first_reclaim_confirmed": True,
                        },
                        {
                            "signal_id": "1d:NYSE:BBB:2026-09-02",
                            "opening_reclaim_lines": ["橙線"],
                            "is_current_period_bar": True,
                            "is_live_session": True,
                        },
                        {
                            "signal_id": "1d:NYSE:HIDDEN:2026-09-02",
                            "opening_reclaim_lines": ["白線"],
                            "is_current_period_bar": False,
                            "is_live_session": False,
                        },
                    ],
                },
            }],
            "weekly_reclaim": {"line_reclaims": {"signals": []}},
        }

        carry_forward_line_reclaim_first_shown(payload, previous, current_time)

        signals = payload["timeframes"][0]["daily_line_reclaims"]["signals"]
        self.assertEqual(signals[0]["first_shown_at_utc"], prior_time)
        self.assertEqual(signals[1]["first_shown_at_utc"], current_time)
        self.assertNotIn("first_shown_at_utc", signals[2])

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
