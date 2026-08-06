#!/usr/bin/env python3
"""Build multi-market Sequential 7/8/9/13 data for GitHub Pages.

The Sequential logic reproduces the supplied Pine Script's close-vs-four-bars-
ago setup, 9-to-13 countdown, opposite-setup reset, and completed-setup
invalidation rules. It only evaluates confirmed candles.

Based on "Discreet sequential counts (7, 8, 9, 13)" by quantifytools,
provided by the user under the Mozilla Public License 2.0.
"""

from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np
import yfinance as yf

from scanner import NEW_YORK, Symbol, chunks, frame_for_symbol, is_regular_session, load_symbols


ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "data" / "sequential.json"
SYMBOLS_FILE = ROOT / "symbols.csv"
TAIPEI = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
TAIFEX_STOCK_FUTURES_URL = "https://www.taifex.com.tw/cht/5/stockMargining"
BINANCE_DATA_URL = "https://data-api.binance.vision/api/v3"
TWSE_COMPANY_INFO_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_COMPANY_INFO_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"


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

# AI Momentum [YinYang] defaults supplied by the user.  These reproduce the
# non-repainting rational-quadratic zones used for the 15-minute and hourly
# TD confirmation.  The five preceding bars deliberately exclude the TD bar.
MOMENTUM_TIMEFRAME_KEYS = {"15m", "1h"}
KERNEL_LOOKBACK = 8
KERNEL_RELATIVE_WEIGHT = 8.0
KERNEL_START_BAR = 25
ZONE_INSIDE_LENGTH = 50
ZONE_OUTSIDE_LENGTH = 75
MOMENTUM_SMOOTHING_LENGTH = 14
MOMENTUM_PRIOR_BARS = 5
# The Trend Trader ribbon supplied by the user uses current-timeframe EMA 50
# and EMA 100.  A yellow AI Momentum line must reach this ribbon's lower edge
# (or break below it) while sloping down within this many bars before a sell TD.
TREND_RIBBON_FAST_LENGTH = 50
TREND_RIBBON_SLOW_LENGTH = 100
YELLOW_TREND_LOOKBACK_BARS = 30
YELLOW_LOWER_EDGE_TOLERANCE_PCT = 0.001
# A recovery signal is valid only when it occurs within 30 completed bars of a
# white/yellow death cross that occurred below the Trend Trader ribbon.
TREND_RECLAIM_DEATH_LOOKBACK_BARS = 30


@dataclass(frozen=True)
class MarketSession:
    timezone: timezone | ZoneInfo
    session_open: clock_time | None = None
    session_close: clock_time | None = None


US_SESSION = MarketSession(NEW_YORK, clock_time(9, 30), clock_time(16, 0))
TW_SESSION = MarketSession(TAIPEI, clock_time(9, 0), clock_time(13, 30))
CRYPTO_SESSION = MarketSession(UTC)


@dataclass(frozen=True)
class Instrument:
    ticker: str
    symbol: str
    exchange: str
    market: str
    session: MarketSession
    name: str | None = None
    industry: str | None = None


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


class HtmlTables(HTMLParser):
    """Tiny dependency-free HTML table reader for the TAIFEX public table."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            self._row.append(" ".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def _http_json_url(url: str) -> object:
    request = Request(url, headers={"User-Agent": "KJ-Radar-System/1.0"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_json(path: str) -> object:
    return _http_json_url(f"{BINANCE_DATA_URL}{path}")


def fetch_taiwan_industries() -> dict[str, str]:
    """Read public listed/OTC company industries for Taiwan signal cards."""
    industries: dict[str, str] = {}
    for source_url in (TWSE_COMPANY_INFO_URL, TPEX_COMPANY_INFO_URL):
        try:
            rows = _http_json_url(source_url)
        except Exception as exc:
            logging.warning("台股產業資料下載失敗：%s", exc)
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("公司代號") or row.get("證券代號") or "").strip().upper()
            industry = str(row.get("產業別") or "").strip()
            if re.fullmatch(r"\d{4,6}[A-Z]?", code) and industry:
                industries[code] = industry
    return industries


def fetch_taifex_stock_futures() -> dict[str, str]:
    """Read the official, current stock-futures underlying list from TAIFEX.

    The first table is ordinary-share stock futures. ETF futures are a separate
    table and intentionally excluded from this Taiwan-stock monitor. Mini and
    standard contracts on the same underlying are deduplicated.
    """
    request = Request(TAIFEX_STOCK_FUTURES_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8", errors="replace")
    parser = HtmlTables()
    parser.feed(page)
    if not parser.tables or len(parser.tables[0]) < 2:
        raise RuntimeError("無法讀取台灣期交所股票期貨標的清單")

    underlyings: dict[str, str] = {}
    for row in parser.tables[0][1:]:
        if len(row) < 4:
            continue
        code = row[2].strip().upper()
        name = re.sub(r"期貨$", "", row[3].strip())
        if re.fullmatch(r"\d{4,6}[A-Z]?", code) and code not in underlyings:
            underlyings[code] = name or code
    if len(underlyings) < 100:
        raise RuntimeError(f"台灣期交所清單格式異常，僅取得 {len(underlyings)} 檔")
    return underlyings


def download_timeframe(
    symbols: list[Symbol], timeframe: Timeframe, batch_size: int = 100
) -> dict[str, pd.DataFrame]:
    """Download one Yahoo Finance timeframe in batches."""
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
            if not {"Close", "High", "Low"}.issubset(frame.columns):
                continue
            clean = frame.dropna(subset=["Close", "High", "Low"]).copy()
            if not clean.empty:
                frames[ticker] = clean
    return frames


def download_yahoo_records(
    instruments: list[Instrument], timeframe: Timeframe
) -> list[tuple[Instrument, pd.DataFrame]]:
    symbols = [Symbol(item.ticker, item.exchange) for item in instruments]
    frames = download_timeframe(symbols, timeframe)
    return [(item, frames[item.ticker]) for item in instruments if item.ticker in frames]


def download_taiwan_records(
    underlyings: dict[str, str], industries: dict[str, str], timeframe: Timeframe
) -> list[tuple[Instrument, pd.DataFrame]]:
    """Resolve Taiwan stock tickers on TWSE first, then TPEX."""
    primary = [
        Instrument(f"{code}.TW", code, "TWSE", "台股", TW_SESSION, name, industries.get(code))
        for code, name in underlyings.items()
    ]
    primary_records = download_yahoo_records(primary, timeframe)
    found = {item.symbol for item, _ in primary_records}
    fallback = [
        Instrument(f"{code}.TWO", code, "TPEX", "台股", TW_SESSION, name, industries.get(code))
        for code, name in underlyings.items()
        if code not in found
    ]
    return primary_records + download_yahoo_records(fallback, timeframe)


def fetch_binance_instruments() -> list[Instrument]:
    """Select the most liquid Binance Spot USDT pairs, excluding stable coins."""
    configured = int(os.getenv("BINANCE_TOP_USDT_PAIRS", "40"))
    if configured < 1 or configured > 100:
        raise ValueError("BINANCE_TOP_USDT_PAIRS 必須介於 1 到 100")
    rows = _http_json("/ticker/24hr")
    if not isinstance(rows, list):
        raise RuntimeError("無法取得幣安 24 小時成交資料")

    stable_bases = {
        "USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "GUSD", "LUSD",
        "FRAX", "USDD", "USDE", "USDS", "USD1", "PYUSD", "RLUSD", "DUSD", "EUR", "TRY",
    }
    leveraged_suffixes = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
    selected: list[tuple[float, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper()
        base = symbol.removesuffix("USDT")
        if (
            not symbol.endswith("USDT")
            or not re.fullmatch(r"[A-Z0-9]+USDT", symbol)
            or base in stable_bases
            or symbol.endswith(leveraged_suffixes)
        ):
            continue
        try:
            volume = float(row.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        if volume > 0:
            selected.append((volume, symbol))
    selected.sort(reverse=True)
    return [
        Instrument(symbol, symbol, "BINANCE", "幣安現貨", CRYPTO_SESSION)
        for _, symbol in selected[:configured]
    ]


def _download_binance_frame(symbol: str, timeframe: Timeframe) -> pd.DataFrame:
    rows = _http_json(f"/klines?symbol={symbol}&interval={timeframe.key}&limit=120")
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    values = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            continue
        values.append(
            {
                "time": pd.to_datetime(int(row[0]), unit="ms", utc=True),
                "Open": float(row[1]),
                "Close": float(row[4]),
                "High": float(row[2]),
                "Low": float(row[3]),
                "Volume": float(row[5]),
            }
        )
    if not values:
        return pd.DataFrame()
    frame = pd.DataFrame(values).set_index("time").sort_index()
    return frame


def download_binance_records(
    instruments: list[Instrument], timeframe: Timeframe
) -> list[tuple[Instrument, pd.DataFrame]]:
    records: list[tuple[Instrument, pd.DataFrame]] = []
    workers = min(8, max(1, len(instruments)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_download_binance_frame, item.ticker, timeframe): item
            for item in instruments
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                frame = future.result()
            except Exception as exc:
                logging.warning("幣安 %s %s 下載失敗：%s", item.ticker, timeframe.label, exc)
                continue
            if not frame.empty:
                records.append((item, frame))
    return records


def confirmed_bars(
    raw: pd.DataFrame, timeframe: Timeframe, session: MarketSession, now: datetime
) -> pd.DataFrame:
    """Keep market-session bars that were completed by ``now``."""
    if raw.empty:
        return raw
    columns = ["Close", "High", "Low"]
    columns.extend(column for column in ("Open", "Volume") if column in raw.columns)
    frame = raw[columns].copy().sort_index()
    index = pd.DatetimeIndex(frame.index)
    now_local = now.astimezone(session.timezone)

    if timeframe.duration is None:
        if index.tz is not None:
            index = index.tz_convert(session.timezone).tz_localize(None)
        frame.index = index
        if session.session_close is None:
            return frame.loc[frame.index.date < now_local.date()]
        completed_today = now_local.time() >= session.session_close
        mask = frame.index.date <= now_local.date() if completed_today else frame.index.date < now_local.date()
        return frame.loc[mask]

    if index.tz is None:
        index = index.tz_localize("UTC")
    frame.index = index.tz_convert(session.timezone)
    if session.session_open is not None and session.session_close is not None:
        frame = frame.loc[
            (frame.index.time >= session.session_open)
            & (frame.index.time < session.session_close)
        ]
    return frame.loc[frame.index + timeframe.duration <= now_local]


def signal_labels(state: SequentialState) -> list[str]:
    """Only the 9 and 13 marks plotted with text in the supplied Pine code."""
    labels: list[str] = []
    if state.buy_setup == 9:
        labels.append("買方 Setup 9")
    if state.buy_countdown == 13:
        labels.append("買方 Countdown 13")
    if state.sell_setup == 9:
        labels.append("賣方 Setup 9")
    if state.sell_countdown == 13:
        labels.append("賣方 Countdown 13")
    return labels


def sequential_history(frame: pd.DataFrame) -> tuple[SequentialState, list[dict[str, object]]]:
    """Evaluate all bars and retain every bar on which 9 or 13 occurred."""
    state = SequentialState()
    if len(frame) < 5:
        return state, []

    close = pd.to_numeric(frame["Close"], errors="coerce").astype(float).tolist()
    high = pd.to_numeric(frame["High"], errors="coerce").astype(float).tolist()
    low = pd.to_numeric(frame["Low"], errors="coerce").astype(float).tolist()

    events: list[dict[str, object]] = []
    for position in range(4, len(frame)):
        current_close = close[position]
        state.buy_setup = (1 if state.buy_setup == 9 else state.buy_setup + 1) if current_close < close[position - 4] else 0
        state.sell_setup = (1 if state.sell_setup == 9 else state.sell_setup + 1) if current_close > close[position - 4] else 0
        prior_buy_countdown = state.buy_countdown
        prior_sell_countdown = state.sell_countdown

        if state.buy_setup == 9:
            state.buy_enabled = True
            state.buy_countdown = 0
            state.sell_enabled = False
            state.sell_countdown = 0
            state.buy_setup_highs.extend(high[position - 8 : position + 1])
        if state.buy_enabled and current_close < low[position - 2]:
            state.buy_countdown += 1
        if prior_buy_countdown == 13:
            state.buy_enabled = False
            state.buy_countdown = 0

        if state.sell_setup == 9:
            state.sell_enabled = True
            state.sell_countdown = 0
            state.buy_enabled = False
            state.buy_countdown = 0
            state.sell_setup_lows.extend(low[position - 8 : position + 1])
        if state.sell_enabled and current_close > high[position - 2]:
            state.sell_countdown += 1
        if prior_sell_countdown == 13:
            state.sell_enabled = False
            state.sell_countdown = 0

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

        labels = signal_labels(state)
        if labels:
            events.append(
                {
                    "position": position,
                    "labels": labels,
                    "side": signal_side(labels),
                    "buy_setup": state.buy_setup,
                    "sell_setup": state.sell_setup,
                    "buy_countdown": state.buy_countdown,
                    "sell_countdown": state.sell_countdown,
                }
            )
    return state, events


def sequential_state(frame: pd.DataFrame) -> tuple[SequentialState, list[str]]:
    """Return the final state; retained for the focused calculation test."""
    state, _ = sequential_history(frame)
    return state, signal_labels(state)


def rational_quadratic(source: pd.Series) -> pd.Series:
    """Non-repainting Rational Quadratic estimate used by KernelFunctions v2.

    The Pine library sums the current bar through ``lookback + startBar``.
    Using a fixed backward-only window preserves that non-repainting behavior.
    """
    values = pd.to_numeric(source, errors="coerce").to_numpy(dtype=float)
    length = len(values)
    max_lag = KERNEL_LOOKBACK + KERNEL_START_BAR
    lags = np.arange(max_lag + 1, dtype=float)
    weights = np.power(
        1 + (np.square(lags) / (KERNEL_LOOKBACK**2 * 2 * KERNEL_RELATIVE_WEIGHT)),
        -KERNEL_RELATIVE_WEIGHT,
    )
    numerator = np.convolve(values, weights, mode="full")[:length]
    missing = np.convolve(
        np.isnan(values).astype(float), np.ones(len(weights)), mode="full"
    )[:length]
    estimate = numerator / weights.sum()
    estimate[:max_lag] = np.nan
    estimate[missing > 0] = np.nan
    return pd.Series(estimate, index=source.index, dtype=float)


def wilder_rsi(close: pd.Series, length: int) -> pd.Series:
    """Wilder RSI, matching the RSI input used by the supplied indicator."""
    change = close.diff()
    gain = change.clip(lower=0)
    loss = (-change.clip(upper=0))
    average_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    average_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + relative_strength))
    return result.where(average_loss != 0, 100.0)


def ai_momentum_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate the bearish parts of the supplied AI Momentum indicator.

    ``yellow_mid`` is the yellow ``zoneMid`` line from AI Momentum.  The
    Trend Trader script is calculated separately as EMA 50 / EMA 100; its
    lower ribbon edge is the only trend-band edge used for the yellow-line
    confirmation.
    """
    columns = [
        "close",
        "white_kernel",
        "yellow_mid",
        "trend_lower_edge",
        "trend_upper_edge",
        "bearish_bar",
        "very_bearish",
    ]
    if not {"Open", "High", "Low", "Close", "Volume"}.issubset(frame.columns):
        return pd.DataFrame(index=frame.index, columns=columns)

    open_price = pd.to_numeric(frame["Open"], errors="coerce")
    high = pd.to_numeric(frame["High"], errors="coerce")
    low = pd.to_numeric(frame["Low"], errors="coerce")
    close = pd.to_numeric(frame["Close"], errors="coerce")
    volume = pd.to_numeric(frame["Volume"], errors="coerce")
    ohlc4 = (open_price + high + low + close) / 4
    rolling_volume = volume.rolling(MOMENTUM_SMOOTHING_LENGTH, min_periods=MOMENTUM_SMOOTHING_LENGTH).sum()
    vwma = (
        (ohlc4 * volume).rolling(MOMENTUM_SMOOTHING_LENGTH, min_periods=MOMENTUM_SMOOTHING_LENGTH).sum()
        / rolling_volume.replace(0, np.nan)
    )

    upper_inside = rational_quadratic(
        high.rolling(ZONE_INSIDE_LENGTH, min_periods=ZONE_INSIDE_LENGTH).max()
    )
    lower_inside = rational_quadratic(
        low.rolling(ZONE_INSIDE_LENGTH, min_periods=ZONE_INSIDE_LENGTH).min()
    )
    lower_outside = rational_quadratic(
        low.rolling(ZONE_OUTSIDE_LENGTH, min_periods=ZONE_OUTSIDE_LENGTH).min()
    )
    yellow_mid = (upper_inside + lower_inside) / 2
    ribbon_fast = close.ewm(
        span=TREND_RIBBON_FAST_LENGTH,
        adjust=False,
        min_periods=TREND_RIBBON_FAST_LENGTH,
    ).mean()
    ribbon_slow = close.ewm(
        span=TREND_RIBBON_SLOW_LENGTH,
        adjust=False,
        min_periods=TREND_RIBBON_SLOW_LENGTH,
    ).mean()
    trend_lower_edge = pd.concat([ribbon_fast, ribbon_slow], axis=1).min(axis=1)
    trend_upper_edge = pd.concat([ribbon_fast, ribbon_slow], axis=1).max(axis=1)
    kernel_close = rational_quadratic(close)
    minimum_vwma = vwma.rolling(MOMENTUM_SMOOTHING_LENGTH, min_periods=MOMENTUM_SMOOTHING_LENGTH).min()
    bearish_bar = kernel_close < rational_quadratic(minimum_vwma)
    very_bearish = bearish_bar & (rational_quadratic(wilder_rsi(close, MOMENTUM_SMOOTHING_LENGTH)) <= 43)

    return pd.DataFrame(
        {
            "close": close,
            "white_kernel": kernel_close,
            "yellow_mid": yellow_mid,
            "trend_lower_edge": trend_lower_edge,
            "trend_upper_edge": trend_upper_edge,
            "bearish_bar": bearish_bar.fillna(False),
            "very_bearish": very_bearish.fillna(False),
        },
        index=frame.index,
    )


def trend_reclaim_events(features: pd.DataFrame | None) -> list[dict[str, int]]:
    """Find: below ribbon → white/yellow death cross → close reclaims white.

    White is AI Momentum's ``kernClose`` and yellow is its ``zoneMid``.  The
    death cross must occur while the candle closes below the lower EMA 50/100
    ribbon edge.  A reclaim needs a completed close to cross above white while
    white is still below yellow, preventing repeated or already-reversed setups.
    """
    if features is None or len(features) < 2:
        return []

    active_death_cross: int | None = None
    events: list[dict[str, int]] = []
    for position in range(1, len(features)):
        row = features.iloc[position]
        previous = features.iloc[position - 1]
        values = (
            row["close"],
            row["white_kernel"],
            row["yellow_mid"],
            row["trend_lower_edge"],
            previous["close"],
            previous["white_kernel"],
            previous["yellow_mid"],
        )
        if not all(np.isfinite(float(value)) for value in values):
            continue

        white = float(row["white_kernel"])
        yellow = float(row["yellow_mid"])
        prior_white = float(previous["white_kernel"])
        prior_yellow = float(previous["yellow_mid"])
        close = float(row["close"])
        prior_close = float(previous["close"])
        below_ribbon = close < float(row["trend_lower_edge"])
        is_death_cross = prior_white >= prior_yellow and white < yellow
        if is_death_cross and below_ribbon:
            active_death_cross = position

        if active_death_cross is None:
            continue
        if position - active_death_cross > TREND_RECLAIM_DEATH_LOOKBACK_BARS:
            active_death_cross = None
            continue

        reclaims_white = prior_close <= prior_white and close > white
        if reclaims_white and white < yellow and position > active_death_cross:
            events.append({"position": position, "death_cross_position": active_death_cross})
            active_death_cross = None
    return events


def momentum_confirmation(
    features: pd.DataFrame | None,
    position: int,
    side: str,
) -> dict[str, object]:
    """Confirm a *sell* TD with the user's yellow-line / ribbon rule.

    A bearish Momentum confirmation is never attached to a buy TD.  For a
    sell TD, search the current and preceding 29 completed bars.  At least one
    must have the AI Momentum yellow line on / below Trend Trader's EMA 50/100
    ribbon lower edge *and* have a negative one-bar yellow-line slope.
    """
    if features is None or position >= len(features) or side != "sell":
        return {"available": False}

    prior_start = max(0, position - MOMENTUM_PRIOR_BARS)
    prior = features.iloc[prior_start:position]
    bearish_count = int(prior["bearish_bar"].fillna(False).astype(bool).sum())
    very_bearish_count = int(prior["very_bearish"].fillna(False).astype(bool).sum())

    match_position: int | None = None
    match_zone = ""
    match_slope: float | None = None
    search_start = max(1, position - YELLOW_TREND_LOOKBACK_BARS + 1)
    for candidate in range(position, search_start - 1, -1):
        yellow = float(features["yellow_mid"].iloc[candidate])
        previous_yellow = float(features["yellow_mid"].iloc[candidate - 1])
        lower_edge = float(features["trend_lower_edge"].iloc[candidate])
        if not all(np.isfinite(value) for value in (yellow, previous_yellow, lower_edge)):
            continue
        slope = yellow - previous_yellow
        edge_tolerance = abs(lower_edge) * YELLOW_LOWER_EDGE_TOLERANCE_PCT
        if yellow > lower_edge + edge_tolerance or slope >= 0:
            continue
        match_position = candidate
        match_zone = "below_ribbon" if yellow < lower_edge else "lower_edge"
        match_slope = slope
        break

    yellow_trend_confirmed = match_position is not None
    return {
        "available": True,
        "prior_window_bars": min(MOMENTUM_PRIOR_BARS, position),
        "prior_bearish_count": bearish_count,
        "prior_very_bearish_count": very_bearish_count,
        "has_prior_bearish_momentum": bearish_count > 0,
        "yellow_lookback_bars": YELLOW_TREND_LOOKBACK_BARS,
        "yellow_match_bars_ago": position - match_position if match_position is not None else None,
        "yellow_zone_position": match_zone,
        "yellow_slope": round(match_slope, 8) if match_slope is not None else None,
        "yellow_trend_confirmed": yellow_trend_confirmed,
        "bearish_confirmed": bool(bearish_count > 0 and yellow_trend_confirmed),
    }


def format_bar_time(index_value: object, timeframe: Timeframe, session: MarketSession) -> str:
    timestamp = pd.Timestamp(index_value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(session.timezone)
    timestamp = timestamp.tz_convert(session.timezone)
    if timeframe.duration is None:
        return timestamp.strftime("%Y-%m-%d 日線")
    zone_name = "台北" if session.timezone == TAIPEI else "ET" if session.timezone == NEW_YORK else "UTC"
    return timestamp.strftime(f"%Y-%m-%d %H:%M {zone_name}")


def occurrence_time_utc(index_value: object, session: MarketSession) -> str:
    timestamp = pd.Timestamp(index_value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(session.timezone)
    return timestamp.tz_convert(UTC).isoformat()


def signal_side(labels: list[str]) -> str:
    if labels and all(label.startswith("買方") for label in labels):
        return "buy"
    if labels and all(label.startswith("賣方") for label in labels):
        return "sell"
    return "mixed"


def signal_sparkline(
    frame: pd.DataFrame, position: int, maximum_bars: int = 30
) -> tuple[list[float], int]:
    """Return recent completed closes and the TD marker's location within them."""
    start = max(0, len(frame) - maximum_bars)
    closes = [round(float(value), 8) for value in frame["Close"].iloc[start:].tolist()]
    return closes, max(0, min(position - start, len(closes) - 1))


def latest_day_change_pct(
    frame: pd.DataFrame, timeframe: Timeframe, session: MarketSession
) -> float | None:
    """Latest completed session's percentage move from the prior session close."""
    close = pd.to_numeric(frame["Close"], errors="coerce")
    if len(close) < 2 or not np.isfinite(float(close.iloc[-1])):
        return None

    if timeframe.duration is None:
        prior_close = float(close.iloc[-2])
    else:
        index = pd.DatetimeIndex(frame.index)
        if index.tz is None:
            index = index.tz_localize(session.timezone)
        else:
            index = index.tz_convert(session.timezone)
        earlier_positions = np.flatnonzero(index.date < index[-1].date())
        if len(earlier_positions) == 0:
            return None
        prior_close = float(close.iloc[int(earlier_positions[-1])])

    latest_close = float(close.iloc[-1])
    if not np.isfinite(prior_close) or prior_close == 0:
        return None
    return round((latest_close / prior_close - 1) * 100, 4)


def collect_signals(
    us_instruments: list[Instrument],
    taiwan_underlyings: dict[str, str],
    taiwan_industries: dict[str, str],
    binance_instruments: list[Instrument],
    timeframe: Timeframe,
    now: datetime,
) -> dict[str, object]:
    records = download_yahoo_records(us_instruments, timeframe)
    records.extend(download_taiwan_records(taiwan_underlyings, taiwan_industries, timeframe))
    records.extend(download_binance_records(binance_instruments, timeframe))
    signals: list[dict[str, object]] = []
    trend_reclaim_signals: list[dict[str, object]] = []
    scanned_by_market: dict[str, int] = {}
    latest_completed: list[tuple[pd.Timestamp, MarketSession]] = []

    for instrument, raw in records:
        frame = confirmed_bars(raw, timeframe, instrument.session, now)
        if len(frame) < 13:
            continue
        scanned_by_market[instrument.market] = scanned_by_market.get(instrument.market, 0) + 1
        _, events = sequential_history(frame)
        latest_completed.append((pd.Timestamp(frame.index[-1]), instrument.session))
        today_change_pct = latest_day_change_pct(frame, timeframe, instrument.session)
        recent_bars = int(os.getenv("RECENT_SIGNAL_BARS", "5"))
        if recent_bars < 1 or recent_bars > 20:
            raise ValueError("RECENT_SIGNAL_BARS 必須介於 1 到 20")
        recent_events = [
            event for event in events
            if len(frame) - 1 - int(event["position"]) < recent_bars
        ]
        features = ai_momentum_features(frame) if timeframe.key in MOMENTUM_TIMEFRAME_KEYS else None
        for event in recent_events:
            position = int(event["position"])
            age_bars = len(frame) - 1 - position
            sparkline, sparkline_signal_index = signal_sparkline(frame, position)
            signals.append(
                {
                "symbol": instrument.symbol,
                "name": instrument.name,
                "industry": instrument.industry,
                    "exchange": instrument.exchange,
                    "market": instrument.market,
                    "bar_time_et": format_bar_time(frame.index[position], timeframe, instrument.session),
                    "occurred_at_utc": occurrence_time_utc(frame.index[position], instrument.session),
                    "age_bars": age_bars,
                    "last_price": round(float(frame["Close"].iloc[position]), 8),
                    "today_change_pct": today_change_pct,
                    "labels": event["labels"],
                    "side": event["side"],
                    "buy_setup": event["buy_setup"],
                    "sell_setup": event["sell_setup"],
                    "buy_countdown": event["buy_countdown"],
                    "sell_countdown": event["sell_countdown"],
                    "momentum": momentum_confirmation(features, position, str(event["side"])),
                    "sparkline": sparkline,
                    "sparkline_signal_index": sparkline_signal_index,
                }
            )

        if timeframe.key in MOMENTUM_TIMEFRAME_KEYS:
            recent_reclaims = [
                event
                for event in trend_reclaim_events(features)
                if len(frame) - 1 - int(event["position"]) < recent_bars
            ]
            for event in recent_reclaims:
                position = int(event["position"])
                death_position = int(event["death_cross_position"])
                sparkline, sparkline_signal_index = signal_sparkline(frame, position)
                sparkline_start = max(0, len(frame) - 30)
                trend_reclaim_signals.append(
                    {
                        "symbol": instrument.symbol,
                        "name": instrument.name,
                        "industry": instrument.industry,
                        "exchange": instrument.exchange,
                        "market": instrument.market,
                        "bar_time_et": format_bar_time(frame.index[position], timeframe, instrument.session),
                        "occurred_at_utc": occurrence_time_utc(frame.index[position], instrument.session),
                        "age_bars": len(frame) - 1 - position,
                        "last_price": round(float(frame["Close"].iloc[position]), 8),
                        "today_change_pct": today_change_pct,
                        "death_cross_time": format_bar_time(
                            frame.index[death_position], timeframe, instrument.session
                        ),
                        "death_cross_bars_ago": position - death_position,
                        "sparkline": sparkline,
                        "sparkline_signal_index": sparkline_signal_index,
                        "sparkline_death_index": (
                            death_position - sparkline_start
                            if death_position >= sparkline_start
                            else None
                        ),
                    }
                )

    signals.sort(key=lambda item: str(item["occurred_at_utc"]), reverse=True)
    trend_reclaim_signals.sort(key=lambda item: str(item["occurred_at_utc"]), reverse=True)
    return {
        "key": timeframe.key,
        "label": timeframe.label,
        "tradingview_interval": timeframe.tradingview_interval,
        "scanned_symbols": sum(scanned_by_market.values()),
        "scanned_by_market": scanned_by_market,
        "recent_bars": int(os.getenv("RECENT_SIGNAL_BARS", "5")),
        "last_completed_bar_et": "已依各市場最後完成 K 棒計算" if latest_completed else None,
        "signals": signals,
        "trend_reclaim_signals": trend_reclaim_signals,
    }


def write_payload(frames: Iterable[dict[str, object]], now: datetime, errors: list[str]) -> None:
    source = (
        "美股與台股資料：Yahoo Finance via yfinance；台股監測清單：公開市場資料整理；"
        "幣安：24 小時成交額最高的 USDT 現貨交易對（預設前 40 檔）與公開 K 線。"
    )
    if errors:
        source += " 本次部分來源未更新：" + "；".join(errors)
    payload = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "market_status": "open" if is_regular_session(now) else "closed",
        "source": source,
        "timeframes": list(frames),
    }
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(NEW_YORK)
    errors: list[str] = []
    us_instruments = [
        Instrument(item.ticker, item.ticker, item.exchange, "美股", US_SESSION, None, item.industry or None)
        for item in load_symbols(SYMBOLS_FILE)
    ]
    try:
        taiwan_underlyings = fetch_taifex_stock_futures()
    except Exception as exc:
        logging.warning("台灣期交所標的清單讀取失敗：%s", exc)
        taiwan_underlyings = {}
        errors.append("台灣期交所標的清單讀取失敗")
    taiwan_industries = fetch_taiwan_industries()
    try:
        binance_instruments = fetch_binance_instruments()
    except Exception as exc:
        logging.warning("幣安標的清單讀取失敗：%s", exc)
        binance_instruments = []
        errors.append("幣安標的清單讀取失敗")

    frames = [
        collect_signals(
            us_instruments,
            taiwan_underlyings,
            taiwan_industries,
            binance_instruments,
            timeframe,
            now,
        )
        for timeframe in TIMEFRAMES
    ]
    write_payload(frames, now, errors)
    logging.info(
        "Sequential 已更新：%s",
        ", ".join(f"{item['label']} {len(item['signals'])} 個訊號" for item in frames),
    )


if __name__ == "__main__":
    main()
