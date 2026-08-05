#!/usr/bin/env python3
"""Create the homepage futures pulse and US pre-market mover data.

GitHub Pages is static, so this script is intentionally run by Actions every
five minutes.  It uses Yahoo Finance data and only labels a stock as a
pre-market mover during the 04:00-09:30 America/New_York session.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import numpy as np
import yfinance as yf

from scanner import NEW_YORK, Symbol, chunks, frame_for_symbol, load_symbols


ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "data" / "market.json"
SYMBOLS_FILE = ROOT / "symbols.csv"
UTC = timezone.utc
PREMARKET_OPEN = clock_time(4, 0)
REGULAR_OPEN = clock_time(9, 30)
REGULAR_CLOSE = clock_time(16, 0)


@dataclass(frozen=True)
class FutureSpec:
    key: str
    label: str
    tickers: tuple[str, ...]
    currency: str
    tradingview_symbol: str


FUTURES = (
    # Yahoo's Taiwan near-month ticker can be unavailable to its global API.
    # IX0126.TW is retained as an explicitly marked fallback quote.
    FutureSpec("taiwan", "台指期", ("WTX&", "IX0126.TW"), "TWD", "TAIFEX:TX1!"),
    FutureSpec("nasdaq", "NASDAQ 100 期貨", ("NQ=F",), "USD", "CME_MINI:NQ1!"),
    FutureSpec("dow", "道瓊期貨", ("YM=F",), "USD", "CBOT_MINI:YM1!"),
    FutureSpec("sox", "SOX 期貨", ("SOX=F",), "USD", "CME_MINI:SOX1!"),
    FutureSpec("russell", "Russell 2000 期貨", ("RTY=F",), "USD", "CME_MINI:RTY1!"),
    # NKD is the USD-denominated CME Nikkei contract. It gives the dashboard
    # an overnight Asia reference while the US market is closed.
    FutureSpec("japan", "日經 225 期貨", ("NKD=F",), "USD", "CME:NKD1!"),
    # Yahoo does not consistently expose KRX's continuous contract. Try a
    # futures identifier first; otherwise label KOSPI 200 spot as a proxy.
    FutureSpec("korea", "南韓 KOSPI 200 期貨", ("KOSPI200=F", "KOSPI200.KS"), "KRW", "KRX:K2I1!"),
)

# Large, liquid names that commonly lead broad US index, technology,
# semiconductor, financial, consumer, industrial, healthcare and energy moves.
PREMARKET_TICKERS = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "ORCL", "NFLX",
    "AMD", "INTC", "MU", "ARM", "QCOM", "TXN", "AMAT", "LRCX", "KLAC", "SMCI",
    "PLTR", "CRM", "ADBE", "NOW", "PANW", "CRWD", "UBER", "ABNB", "COIN", "HOOD",
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "BRK-B", "BLK",
    "LLY", "UNH", "JNJ", "ABBV", "MRK", "ISRG", "TMO", "AMGN", "PFE", "GILD",
    "WMT", "COST", "HD", "MCD", "NKE", "DIS", "SBUX", "KO", "PEP", "TGT",
    "XOM", "CVX", "COP", "GE", "CAT", "BA", "DE", "HON", "LMT", "RTX",
)

PREMARKET_FALLBACKS = {
    "BRK-B": Symbol("BRK-B", "NYSE", "綜合企業"),
    "COIN": Symbol("COIN", "NASDAQ", "加密資產平台"),
    "HOOD": Symbol("HOOD", "NASDAQ", "金融科技"),
    "MA": Symbol("MA", "NYSE", "支付網路"),
    "V": Symbol("V", "NYSE", "支付網路"),
}


def _positive_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a single-ticker frame with a UTC index and valid closing prices."""
    if frame.empty or "Close" not in frame.columns:
        return pd.DataFrame()
    result = frame.copy()
    result["Close"] = pd.to_numeric(result["Close"], errors="coerce")
    result = result.dropna(subset=["Close"]).sort_index()
    if result.empty:
        return result
    index = pd.DatetimeIndex(result.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    result.index = index.tz_convert(UTC)
    return result


def download_future(ticker: str) -> pd.DataFrame:
    """Load one-minute futures bars for the pulse and its intraday sparkline.

    GitHub Actions still publishes on its five-minute schedule, but taking the
    most recent one-minute bar makes each published quote as current as that
    schedule permits.
    """
    try:
        raw = yf.download(
            ticker,
            period="5d",
            interval="1m",
            auto_adjust=False,
            prepost=True,
            progress=False,
            threads=False,
            timeout=20,
            multi_level_index=False,
        )
    except Exception as exc:
        logging.warning("Future download failed for %s: %s", ticker, exc)
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        raw = frame_for_symbol(raw, ticker, 1)
    return clean_frame(raw)


def compact_intraday_closes(frame: pd.DataFrame, latest_time: pd.Timestamp, maximum: int = 72) -> list[float]:
    """Return a small, current-session close series safe to ship to the browser."""
    current_session = frame.loc[pd.Index(frame.index.date) == latest_time.date(), "Close"].dropna()
    if current_session.empty:
        return []
    values = current_session.astype(float).to_numpy()
    if len(values) > maximum:
        positions = np.linspace(0, len(values) - 1, maximum, dtype=int)
        values = values[positions]
    return [round(float(value), 4) for value in values]


def future_quote(spec: FutureSpec) -> dict[str, object]:
    """Fetch one quote, moving to its configured fallback when necessary."""
    for index, ticker in enumerate(spec.tickers):
        frame = download_future(ticker)
        if len(frame) < 2:
            continue
        last_price = float(frame["Close"].iloc[-1])
        latest_time = pd.Timestamp(frame.index[-1])
        dates = pd.Index(frame.index.date)
        previous_rows = frame.loc[dates < latest_time.date()]
        baseline = (
            float(previous_rows["Close"].iloc[-1])
            if not previous_rows.empty
            else float(frame["Close"].iloc[-2])
        )
        change = last_price - baseline
        change_pct = (change / baseline * 100) if baseline else 0.0
        return {
            "key": spec.key,
            "label": spec.label,
            "ticker": ticker,
            "currency": spec.currency,
            "last_price": round(last_price, 4),
            "change": round(change, 4),
            "change_pct": round(change_pct, 3),
            "as_of_utc": latest_time.isoformat(),
            "sparkline": compact_intraday_closes(frame, latest_time),
            "quote_interval_minutes": 1,
            "fallback_quote": index > 0,
            "quote_note": "KOSPI 200 現貨指數替代報價" if spec.key == "korea" and index > 0 else "",
            "tradingview_symbol": spec.tradingview_symbol,
        }
    return {
        "key": spec.key,
        "label": spec.label,
        "ticker": spec.tickers[0],
        "currency": spec.currency,
        "unavailable": True,
        "tradingview_symbol": spec.tradingview_symbol,
    }


def download_premarket_frames(symbols: list[Symbol]) -> dict[str, pd.DataFrame]:
    """Download extended-hours one-minute bars in reasonably sized batches."""
    frames: dict[str, pd.DataFrame] = {}
    for batch in chunks(symbols, 35):
        tickers = [item.ticker for item in batch]
        try:
            response = yf.download(
                tickers=tickers,
                period="5d",
                interval="1m",
                group_by="ticker",
                auto_adjust=False,
                prepost=True,
                progress=False,
                threads=True,
                timeout=30,
                multi_level_index=True,
            )
        except Exception as exc:
            logging.warning("Pre-market download failed: %s", exc)
            continue
        for ticker in tickers:
            frame = frame_for_symbol(response, ticker, len(tickers))
            cleaned = clean_frame(frame)
            if not cleaned.empty:
                frames[ticker] = cleaned
    return frames


def premarket_mover(
    symbol: Symbol, raw_frame: pd.DataFrame, now: datetime, threshold_pct: float
) -> dict[str, object] | None:
    """Return a mover only for the current US pre-market session."""
    if raw_frame.empty:
        return None
    frame = raw_frame.copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_convert(NEW_YORK)
    local_now = now.astimezone(NEW_YORK)
    if local_now.weekday() >= 5 or not PREMARKET_OPEN <= local_now.time() < REGULAR_OPEN:
        return None

    today = local_now.date()
    premarket = frame.loc[
        (frame.index.date == today)
        & (frame.index.time >= PREMARKET_OPEN)
        & (frame.index.time < REGULAR_OPEN)
        & (frame.index <= local_now)
    ]
    if premarket.empty:
        return None
    latest = premarket.iloc[-1]
    latest_time = pd.Timestamp(premarket.index[-1])
    regular = frame.loc[
        (frame.index.date < today)
        & (frame.index.time >= REGULAR_OPEN)
        & (frame.index.time < REGULAR_CLOSE)
    ]
    if regular.empty:
        return None
    previous_close = float(regular["Close"].iloc[-1])
    last_price = float(latest["Close"])
    if previous_close <= 0:
        return None
    change_pct = (last_price / previous_close - 1) * 100
    if abs(change_pct) < threshold_pct:
        return None
    return {
        "symbol": symbol.ticker,
        "exchange": symbol.exchange,
        "industry": symbol.industry,
        "last_price": round(last_price, 4),
        "previous_close": round(previous_close, 4),
        "change": round(last_price - previous_close, 4),
        "change_pct": round(change_pct, 3),
        "direction": "up" if change_pct > 0 else "down",
        "bar_time_et": latest_time.strftime("%Y-%m-%d %H:%M ET"),
        "occurred_at_utc": latest_time.tz_convert(UTC).isoformat(),
    }


def selected_premarket_symbols(all_symbols: Iterable[Symbol]) -> list[Symbol]:
    lookup = {item.ticker: item for item in all_symbols}
    return [
        lookup[ticker] if ticker in lookup else PREMARKET_FALLBACKS[ticker]
        for ticker in PREMARKET_TICKERS
    ]


def write_payload(payload: dict[str, object]) -> None:
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(UTC)
    threshold_pct = _float_env("PREMARKET_ABNORMAL_PCT", 2.0, 0.1, 25.0)
    max_movers = _positive_int_env("PREMARKET_MAX_MOVERS", 12, 1, 30)
    errors: list[str] = []

    futures: list[dict[str, object]] = []
    for spec in FUTURES:
        try:
            futures.append(future_quote(spec))
        except Exception as exc:
            logging.warning("Future quote failed for %s: %s", spec.label, exc)
            futures.append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "ticker": spec.tickers[0],
                    "currency": spec.currency,
                    "unavailable": True,
                    "tradingview_symbol": spec.tradingview_symbol,
                }
            )

    try:
        symbols = selected_premarket_symbols(load_symbols(SYMBOLS_FILE))
        frames = download_premarket_frames(symbols)
        movers = [
            result
            for item in symbols
            if (result := premarket_mover(item, frames.get(item.ticker, pd.DataFrame()), now, threshold_pct))
            is not None
        ]
    except Exception as exc:
        logging.warning("Pre-market scan failed: %s", exc)
        symbols, frames, movers = [], {}, []
        errors.append("盤前指標股資料暫時無法取得")

    movers.sort(key=lambda item: abs(float(item["change_pct"])), reverse=True)
    market_open = now.astimezone(NEW_YORK)
    premarket_active = (
        market_open.weekday() < 5 and PREMARKET_OPEN <= market_open.time() < REGULAR_OPEN
    )
    write_payload(
        {
            "updated_at_utc": now.isoformat(),
            "futures": futures,
            "premarket": {
                "active": premarket_active,
                "threshold_pct": threshold_pct,
                "scanned_symbols": len(frames),
                "movers": movers[:max_movers],
            },
            "source": "Yahoo Finance via yfinance；期貨與盤前報價可能延遲。",
            "errors": errors,
        }
    )
    logging.info("Market pulse refreshed: %s futures, %s pre-market movers", len(futures), len(movers))


if __name__ == "__main__":
    main()
