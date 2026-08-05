#!/usr/bin/env python3
"""Build multi-timeframe Sequential 7/8/9/13 monitor data for GitHub Pages.

This reproduces the supplied Pine Script's close-vs-four-bars-ago setup,
9-to-13 countdown, opposite-setup reset, and completed-setup invalidation
rules.  It only evaluates confirmed bars, so an in-progress candle cannot
change a published count.

Based on "Discreet sequential counts (7, 8, 9, 13)" by quantifytools,
provided by the user under the Mozilla Public License 2.0.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import yfinance as yf

from scanner import NEW_YORK, Symbol, chunks, frame_for_symbol, is_regular_session, load_symbols


ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "data" / "sequential.json"
SYMBOLS_FILE = ROOT / "symbols.csv"


@dataclass(frozen=True)
class Timeframe:
    key: str
    label: str
    yahoo_interval: str
    yahoo_period: str
    tradingview_interval: str
    duration: timedelta | None


TIMEFRAMES = (
    Timeframe("15m", "15 分鐘", "15m", "60d", "15", timedelta(minutes=15)),
    Timeframe("1h", "1 小時", "1h", "1y", "60", timedelta(hours=1)),
    Timeframe("1d", "日線", "1d", "2y", "D", None),
)


@dataclass
class SequentialState:
    buy_setup: int = 0
    sell_setup: int = 0
    buy_countdown: int = 0
    sell_countdown: int = 0
    buy_enabled: bool = False
    sell_enabled: bool = False
    buy_setup_highs: list[float] | None = None
    sell_setup_lows: list[float] | None = None

    def __post_init__(self) -> None:
        if self.buy_setup_highs is None:
            self.buy_setup_highs = []
        if self.sell_setup_lows is None:
            self.sell_setup_lows = []


def download_timeframe(
    symbols: list[Symbol], timeframe: Timeframe, batch_size: int = 100
) -> dict[str, pd.DataFrame]:
    """Download all requested symbols in batches for one timeframe."""
    frames: dict[str, pd.DataFrame] = {}
    for batch in chunks(symbols, batch_size):
        tickers = [item.ticker for item in batch]
        try:
            response = yf.download(
                tickers=tickers,
                period=timeframe.yahoo_period,
                interval=timeframe.yahoo_interval,
                group_by="ticker",
                auto_adjust=False,
                prepost=False,
                progress=False,
                threads=True,
                timeout=30,
                multi_level_index=True,
            )
        except Exception as exc:
            logging.warning("%s 資料下載失敗：%s", timeframe.label, exc)
            continue

        for ticker in tickers:
            frame = frame_for_symbol(response, ticker, len(tickers))
            if {"Close", "High", "Low"}.issubset(frame.columns):
                frames[ticker] = frame.dropna(subset=["Close", "High", "Low"]).copy()
    return frames


def confirmed_regular_bars(
    raw: pd.DataFrame, timeframe: Timeframe, now: datetime
) -> pd.DataFrame:
    """Keep regular-session bars that have completed by ``now`` in New York."""
    if raw.empty:
        return raw

    frame = raw[["Close", "High", "Low"]].copy().sort_index()
    index = pd.DatetimeIndex(frame.index)
    now_et = now.astimezone(NEW_YORK)

    if timeframe.duration is None:
        # Yahoo daily timestamps are date labels.  Today's daily candle is only
        # confirmed at the regular-session close; prior dates are always safe.
        if index.tz is not None:
            index = index.tz_convert(NEW_YORK).tz_localize(None)
        frame.index = index
        today = now_et.date()
        if now_et.weekday() < 5 and now_et.time() < clock_time(16, 0):
            return frame.loc[frame.index.date < today]
        return frame.loc[frame.index.date <= today]

    if index.tz is None:
        index = index.tz_localize("UTC")
    frame.index = index.tz_convert(NEW_YORK)
    frame = frame.loc[
        (frame.index.time >= clock_time(9, 30))
        & (frame.index.time < clock_time(16, 0))
    ]
    if frame.empty:
        return frame
    return frame.loc[frame.index + timeframe.duration <= now_et]


def sequential_state(frame: pd.DataFrame) -> tuple[SequentialState, list[str]]:
    """Evaluate the supplied Pine algorithm over a completed OHLC frame."""
    state = SequentialState()
    if len(frame) < 5:
        return state, []

    close = pd.to_numeric(frame["Close"], errors="coerce").astype(float).tolist()
    high = pd.to_numeric(frame["High"], errors="coerce").astype(float).tolist()
    low = pd.to_numeric(frame["Low"], errors="coerce").astype(float).tolist()

    for position in range(4, len(frame)):
        current_close = close[position]

        # Sequential setup counts: close relative to the close four bars ago.
        state.buy_setup = (
            1 if state.buy_setup == 9 else state.buy_setup + 1
        ) if current_close < close[position - 4] else 0
        state.sell_setup = (
            1 if state.sell_setup == 9 else state.sell_setup + 1
        ) if current_close > close[position - 4] else 0

        prior_buy_countdown = state.buy_countdown
        prior_sell_countdown = state.sell_countdown

        # Buy setup 9 enables a buy countdown and cancels the sell countdown.
        if state.buy_setup == 9:
            state.buy_enabled = True
            state.buy_countdown = 0
            state.sell_enabled = False
            state.sell_countdown = 0
            state.buy_setup_highs.extend(high[position - 8 : position + 1])

        # Countdown test is exactly close < low[2].
        if state.buy_enabled and position >= 2 and current_close < low[position - 2]:
            state.buy_countdown += 1

        # Pine checks the prior bar's count, so 13 is visible for one bar.
        if prior_buy_countdown == 13:
            state.buy_enabled = False
            state.buy_countdown = 0

        # Sell setup 9 enables a sell countdown and cancels the buy countdown.
        if state.sell_setup == 9:
            state.sell_enabled = True
            state.sell_countdown = 0
            state.buy_enabled = False
            state.buy_countdown = 0
            state.sell_setup_lows.extend(low[position - 8 : position + 1])

        # Countdown test is exactly close > high[2].
        if state.sell_enabled and position >= 2 and current_close > high[position - 2]:
            state.sell_countdown += 1

        if prior_sell_countdown == 13:
            state.sell_enabled = False
            state.sell_countdown = 0

        # The Pine script retains completed-setup highs/lows while that
        # countdown stays active, then invalidates on a breakout/breakdown.
        if state.buy_enabled and state.buy_setup_highs and current_close > max(state.buy_setup_highs):
            state.buy_enabled = False
            state.buy_countdown = 0
        if state.sell_enabled and state.sell_setup_lows and current_close < min(state.sell_setup_lows):
            state.sell_enabled = False
            state.sell_countdown = 0
        if not state.buy_enabled:
            state.buy_setup_highs.clear()
        if not state.sell_enabled:
            state.sell_setup_lows.clear()

    labels: list[str] = []
    if state.buy_setup in {7, 8, 9}:
        labels.append(f"買方 Setup {state.buy_setup}")
    if state.buy_countdown == 13:
        labels.append("買方 Countdown 13")
    if state.sell_setup in {7, 8, 9}:
        labels.append(f"賣方 Setup {state.sell_setup}")
    if state.sell_countdown == 13:
        labels.append("賣方 Countdown 13")
    return state, labels


def format_bar_time(index_value: object, timeframe: Timeframe) -> str:
    timestamp = pd.Timestamp(index_value)
    if timeframe.duration is None:
        return timestamp.strftime("%Y-%m-%d 日線")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(NEW_YORK)
    return timestamp.tz_convert(NEW_YORK).strftime("%Y-%m-%d %H:%M ET")


def signal_side(labels: list[str]) -> str:
    if labels and all(label.startswith("買方") for label in labels):
        return "buy"
    if labels and all(label.startswith("賣方") for label in labels):
        return "sell"
    return "mixed"


def collect_signals(
    symbols: list[Symbol], timeframe: Timeframe, now: datetime
) -> dict[str, object]:
    frames = download_timeframe(symbols, timeframe)
    exchanges = {item.ticker: item.exchange for item in symbols}
    signals: list[dict[str, object]] = []
    latest_completed: list[pd.Timestamp] = []

    for ticker, raw in frames.items():
        frame = confirmed_regular_bars(raw, timeframe, now)
        if len(frame) < 13:
            continue
        state, labels = sequential_state(frame)
        latest_completed.append(pd.Timestamp(frame.index[-1]))
        if not labels:
            continue
        signals.append(
            {
                "symbol": ticker,
                "exchange": exchanges[ticker],
                "bar_time_et": format_bar_time(frame.index[-1], timeframe),
                "last_price": round(float(frame["Close"].iloc[-1]), 2),
                "labels": labels,
                "side": signal_side(labels),
                "buy_setup": state.buy_setup,
                "sell_setup": state.sell_setup,
                "buy_countdown": state.buy_countdown,
                "sell_countdown": state.sell_countdown,
            }
        )

    signals.sort(key=lambda item: (item["symbol"], item["labels"]))
    latest = max(latest_completed) if latest_completed else None
    return {
        "key": timeframe.key,
        "label": timeframe.label,
        "tradingview_interval": timeframe.tradingview_interval,
        "scanned_symbols": len(frames),
        "last_completed_bar_et": format_bar_time(latest, timeframe) if latest is not None else None,
        "signals": signals,
    }


def write_payload(frames: Iterable[dict[str, object]], now: datetime) -> None:
    payload = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "market_status": "open" if is_regular_session(now) else "closed",
        "source": "Yahoo Finance via yfinance；已完成 K 棒；依 quantifytools Pine Script 的 Sequential 計數規則重製。研究監控用途，不構成投資建議。",
        "timeframes": list(frames),
    }
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(NEW_YORK)
    symbols = load_symbols(SYMBOLS_FILE)
    frames = [collect_signals(symbols, timeframe, now) for timeframe in TIMEFRAMES]
    write_payload(frames, now)
    logging.info(
        "Sequential 已更新：%s",
        ", ".join(f"{item['label']} {len(item['signals'])} 個訊號" for item in frames),
    )


if __name__ == "__main__":
    main()
