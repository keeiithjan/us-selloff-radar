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
import yfinance as yf

from scanner import NEW_YORK, Symbol, chunks, frame_for_symbol, is_regular_session, load_symbols


ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "data" / "sequential.json"
SYMBOLS_FILE = ROOT / "symbols.csv"
TAIPEI = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
TAIFEX_STOCK_FUTURES_URL = "https://www.taifex.com.tw/cht/5/stockMargining"
BINANCE_DATA_URL = "https://data-api.binance.vision/api/v3"


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


def _http_json(path: str) -> object:
    request = Request(
        f"{BINANCE_DATA_URL}{path}", headers={"User-Agent": "us-selloff-radar/1.0"}
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_taifex_stock_futures() -> dict[str, str]:
    """Read the official, current stock-futures underlying list from TAIFEX.

    The first table is ordinary-share stock futures. ETF futures are a separate
    table and intentionally excluded from this "個股期貨" monitor. Mini and
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
    underlyings: dict[str, str], timeframe: Timeframe
) -> list[tuple[Instrument, pd.DataFrame]]:
    """Resolve .TW first, then .TWO for individual-futures underlyings."""
    primary = [
        Instrument(f"{code}.TW", code, "TWSE", "台股個股期貨標的", TW_SESSION, name)
        for code, name in underlyings.items()
    ]
    primary_records = download_yahoo_records(primary, timeframe)
    found = {item.symbol for item, _ in primary_records}
    fallback = [
        Instrument(f"{code}.TWO", code, "TPEX", "台股個股期貨標的", TW_SESSION, name)
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
                "Close": float(row[4]),
                "High": float(row[2]),
                "Low": float(row[3]),
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
    frame = raw[["Close", "High", "Low"]].copy().sort_index()
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


def collect_signals(
    us_instruments: list[Instrument],
    taiwan_underlyings: dict[str, str],
    binance_instruments: list[Instrument],
    timeframe: Timeframe,
    now: datetime,
) -> dict[str, object]:
    records = download_yahoo_records(us_instruments, timeframe)
    records.extend(download_taiwan_records(taiwan_underlyings, timeframe))
    records.extend(download_binance_records(binance_instruments, timeframe))
    signals: list[dict[str, object]] = []
    scanned_by_market: dict[str, int] = {}
    latest_completed: list[tuple[pd.Timestamp, MarketSession]] = []

    for instrument, raw in records:
        frame = confirmed_bars(raw, timeframe, instrument.session, now)
        if len(frame) < 13:
            continue
        scanned_by_market[instrument.market] = scanned_by_market.get(instrument.market, 0) + 1
        _, events = sequential_history(frame)
        latest_completed.append((pd.Timestamp(frame.index[-1]), instrument.session))
        recent_bars = int(os.getenv("RECENT_SIGNAL_BARS", "5"))
        if recent_bars < 1 or recent_bars > 20:
            raise ValueError("RECENT_SIGNAL_BARS 必須介於 1 到 20")
        for event in events:
            position = int(event["position"])
            age_bars = len(frame) - 1 - position
            if age_bars >= recent_bars:
                continue
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
                    "labels": event["labels"],
                    "side": event["side"],
                    "buy_setup": event["buy_setup"],
                    "sell_setup": event["sell_setup"],
                    "buy_countdown": event["buy_countdown"],
                    "sell_countdown": event["sell_countdown"],
                }
            )

    signals.sort(key=lambda item: str(item["occurred_at_utc"]), reverse=True)
    return {
        "key": timeframe.key,
        "label": timeframe.label,
        "tradingview_interval": timeframe.tradingview_interval,
        "scanned_symbols": sum(scanned_by_market.values()),
        "scanned_by_market": scanned_by_market,
        "recent_bars": int(os.getenv("RECENT_SIGNAL_BARS", "5")),
        "last_completed_bar_et": "已依各市場最後完成 K 棒計算" if latest_completed else None,
        "signals": signals,
    }


def write_payload(frames: Iterable[dict[str, object]], now: datetime, errors: list[str]) -> None:
    source = (
        "美股與台股資料：Yahoo Finance via yfinance；台股個股期貨清單：台灣期交所公開資料；"
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
    try:
        binance_instruments = fetch_binance_instruments()
    except Exception as exc:
        logging.warning("幣安標的清單讀取失敗：%s", exc)
        binance_instruments = []
        errors.append("幣安標的清單讀取失敗")

    frames = [
        collect_signals(us_instruments, taiwan_underlyings, binance_instruments, timeframe, now)
        for timeframe in TIMEFRAMES
    ]
    write_payload(frames, now, errors)
    logging.info(
        "Sequential 已更新：%s",
        ", ".join(f"{item['label']} {len(item['signals'])} 個訊號" for item in frames),
    )


if __name__ == "__main__":
    main()
