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
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np
import yfinance as yf

from scanner import NEW_YORK, Symbol, chunks, frame_for_symbol, load_symbols
from sequential import ai_momentum_features, sequential_history, trend_reclaim_events


ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "data" / "market.json"
SYMBOLS_FILE = ROOT / "symbols.csv"
UTC = timezone.utc
TAIPEI = ZoneInfo("Asia/Taipei")
PREMARKET_OPEN = clock_time(4, 0)
REGULAR_OPEN = clock_time(9, 30)
REGULAR_CLOSE = clock_time(16, 0)
BINANCE_EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
BINANCE_TICKERS_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
TAIWAN_INDEX_TICKER = "^TWII"
# Binance uses BRKB for Berkshire B, while Yahoo/TradingView use BRK-B.
BINANCE_STOCK_ALIASES = {"BRKB": "BRK-B"}


@dataclass(frozen=True)
class FutureSpec:
    key: str
    label: str
    tickers: tuple[str, ...]
    currency: str
    tradingview_symbol: str


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


def taiwan_weighted_technical_1h() -> dict[str, object]:
    """Build a compact, completed-bar 1-hour TAIEX technical payload.

    It reuses the dashboard's TD Sequential implementation and its white/yellow
    momentum line plus EMA 50/100 trend-band calculation.  The page receives
    only the latest 84 completed bars, rather than embedding an opaque chart.
    """
    try:
        raw = yf.download(
            TAIWAN_INDEX_TICKER,
            period="60d",
            interval="60m",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=25,
            multi_level_index=False,
        )
    except Exception as exc:
        logging.warning("Taiwan weighted 1h download failed: %s", exc)
        return {"available": False, "reason": "台灣加權 1 小時資料暫時無法取得。"}
    if raw.empty or not {"Open", "High", "Low", "Close", "Volume"}.issubset(raw.columns):
        return {"available": False, "reason": "台灣加權 1 小時資料不足。"}

    frame = raw.copy()
    for column in ("Open", "High", "Low", "Close", "Volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).sort_index()
    # The final bar can still be forming while Taiwan is open.  Excluding it
    # keeps the TD and crossover calculations equivalent to confirmed bars.
    if len(frame) > 2:
        frame = frame.iloc[:-1]
    if len(frame) < 130:
        return {"available": False, "reason": "台灣加權 1 小時已完成 K 棒不足，暫無法計算趨勢帶。"}

    features = ai_momentum_features(frame)
    _, sequential_events = sequential_history(frame)
    reclaim_events = trend_reclaim_events(features)
    start = max(0, len(frame) - 84)
    labels_by_position: dict[int, list[str]] = {}
    for event in sequential_events:
        position = int(event["position"])
        if position >= start:
            labels_by_position[position] = [str(label) for label in event["labels"]]

    recent_td_events: list[dict[str, object]] = []
    for event in sequential_events:
        position = int(event["position"])
        if position < start:
            continue
        timestamp = pd.Timestamp(frame.index[position])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(TAIPEI)
        else:
            timestamp = timestamp.tz_convert(TAIPEI)
        recent_td_events.append(
            {
                "time": timestamp.isoformat(),
                "labels": [str(label) for label in event["labels"]],
                "age_bars": len(frame) - 1 - position,
            }
        )

    def finite(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return round(number, 2) if np.isfinite(number) else None

    bars: list[dict[str, object]] = []
    for position in range(start, len(frame)):
        timestamp = pd.Timestamp(frame.index[position])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(TAIPEI)
        else:
            timestamp = timestamp.tz_convert(TAIPEI)
        feature = features.iloc[position]
        bars.append(
            {
                "time": timestamp.isoformat(),
                "open": finite(frame["Open"].iloc[position]),
                "high": finite(frame["High"].iloc[position]),
                "low": finite(frame["Low"].iloc[position]),
                "close": finite(frame["Close"].iloc[position]),
                "white": finite(feature["white_kernel"]),
                "yellow": finite(feature["yellow_mid"]),
                "ribbon_lower": finite(feature["trend_lower_edge"]),
                "ribbon_upper": finite(feature["trend_upper_edge"]),
                "td_labels": labels_by_position.get(position, []),
            }
        )

    latest = bars[-1]
    price = float(latest["close"])
    ribbon_lower = latest["ribbon_lower"]
    ribbon_upper = latest["ribbon_upper"]
    if ribbon_lower is None or ribbon_upper is None:
        ribbon_position = "資料不足"
    elif price > float(ribbon_upper):
        ribbon_position = "趨勢帶上方"
    elif price < float(ribbon_lower):
        ribbon_position = "趨勢帶下方"
    else:
        ribbon_position = "趨勢帶內"
    white = latest["white"]
    yellow = latest["yellow"]
    if white is None or yellow is None:
        line_state = "白／黃線資料不足"
    elif float(white) > float(yellow):
        line_state = "白線在黃線上方"
    else:
        line_state = "白線在黃線下方"
    latest_reclaim = reclaim_events[-1] if reclaim_events else None
    reclaim_age = len(frame) - 1 - int(latest_reclaim["position"]) if latest_reclaim else None
    return {
        "available": True,
        "symbol": "TVC:TWII",
        "interval": "60",
        "bars": bars,
        "updated_at_utc": latest["time"],
        "latest_price": latest["close"],
        "latest_td_labels": latest["td_labels"],
        "recent_td_events": recent_td_events[-6:],
        "trend": {
            "ribbon_position": ribbon_position,
            "line_state": line_state,
            "white": white,
            "yellow": yellow,
            "ribbon_lower": ribbon_lower,
            "ribbon_upper": ribbon_upper,
            "last_long_reclaim_bars_ago": reclaim_age,
        },
        "source": "台灣加權指數 1 小時 OHLCV：Yahoo Finance via yfinance；僅納入已完成 K 棒。",
    }


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
        "sparkline": compact_intraday_closes(premarket, latest_time),
    }


def latest_regular_close(raw_frame: pd.DataFrame, now: datetime) -> float | None:
    """Return a symbol's latest completed US regular-session close when available."""
    if raw_frame.empty:
        return None
    frame = raw_frame.copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_convert(NEW_YORK)
    local_now = now.astimezone(NEW_YORK)
    is_after_regular_close = local_now.time() >= REGULAR_CLOSE
    dates = frame.index.date
    # The regular session starts at 09:30, not the 04:00 extended-hours open.
    regular = frame.loc[
        (frame.index.time >= REGULAR_OPEN)
        & (frame.index.time < REGULAR_CLOSE)
        & (frame.index <= local_now)
        & ((dates < local_now.date()) | (is_after_regular_close & (dates == local_now.date())))
    ]
    if regular.empty:
        return None
    close = float(regular["Close"].iloc[-1])
    return close if close > 0 else None


def download_binance_json(url: str) -> object | None:
    """Read one fixed public Binance USDⓈ-M endpoint without an API key."""
    request = Request(url, headers={"User-Agent": "us-selloff-radar/1.0"})
    try:
        with urlopen(request, timeout=15) as response:  # nosec B310 - fixed Binance HTTPS endpoint
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        logging.warning("Binance public data request failed: %s", exc)
        return None


def discover_binance_equity_contracts(all_symbols: Iterable[Symbol]) -> dict[str, Symbol]:
    """Match the user's watchlist to live USDT equity perpetual contracts.

    The exchange list is fetched each scan: new listings are automatically
    included and delisted/paused contracts are automatically excluded.
    """
    payload = download_binance_json(BINANCE_EXCHANGE_INFO_URL)
    if not isinstance(payload, dict):
        return {}
    watchlist = {item.ticker: item for item in all_symbols}
    matches: dict[str, Symbol] = {}
    for contract in payload.get("symbols", []):
        if not isinstance(contract, dict):
            continue
        if (
            contract.get("quoteAsset") != "USDT"
            or contract.get("underlyingType") != "EQUITY"
            or contract.get("contractType") != "TRADIFI_PERPETUAL"
            or contract.get("status") != "TRADING"
        ):
            continue
        base_asset = str(contract.get("baseAsset", "")).upper()
        cash_ticker = BINANCE_STOCK_ALIASES.get(base_asset, base_asset)
        stock = watchlist.get(cash_ticker)
        contract_symbol = str(contract.get("symbol", "")).upper()
        if stock and contract_symbol:
            matches[contract_symbol] = stock
    return matches


def download_binance_tickers() -> dict[str, dict[str, object]]:
    """Load all current 24-hour quotes in one request, then filter locally."""
    payload = download_binance_json(BINANCE_TICKERS_URL)
    if not isinstance(payload, list):
        return {}
    return {
        str(item.get("symbol", "")).upper(): item
        for item in payload
        if isinstance(item, dict) and item.get("symbol")
    }


def download_binance_sparkline(contract_symbol: str) -> list[float]:
    """Return the latest 60 one-minute closes for a displayed Binance card."""
    url = (
        "https://fapi.binance.com/fapi/v1/klines?symbol="
        f"{contract_symbol}&interval=1m&limit=60"
    )
    payload = download_binance_json(url)
    if not isinstance(payload, list):
        return []
    closes: list[float] = []
    for candle in payload:
        try:
            closes.append(round(float(candle[4]), 4))
        except (IndexError, TypeError, ValueError):
            continue
    return closes


def binance_equity_movers(
    contracts: dict[str, Symbol],
    raw_frames: dict[str, pd.DataFrame],
    now: datetime,
    threshold_pct: float,
) -> list[dict[str, object]]:
    """Create abnormal-move cards for all discovered Binance stock contracts."""
    tickers = download_binance_tickers()
    movers: list[dict[str, object]] = []
    for contract_symbol, stock in contracts.items():
        quote = tickers.get(contract_symbol)
        if not quote:
            continue
        try:
            last_price = float(quote["lastPrice"])
            fallback_baseline = float(quote["openPrice"])
            as_of = pd.Timestamp(int(quote["closeTime"]), unit="ms", tz=UTC)
        except (KeyError, TypeError, ValueError):
            continue
        if last_price <= 0 or fallback_baseline <= 0:
            continue

        previous_close = latest_regular_close(raw_frames.get(stock.ticker, pd.DataFrame()), now)
        reference_label = f"{stock.ticker} 最近一般盤收盤"
        if previous_close is None:
            previous_close = fallback_baseline
            reference_label = "Binance 24 小時開盤"
        change_pct = (last_price / previous_close - 1) * 100
        if abs(change_pct) < threshold_pct:
            continue
        industry = " · ".join(
            part for part in (stock.ticker, stock.industry, "股票永續合約（非現股）") if part
        )
        movers.append(
            {
                "symbol": contract_symbol,
                "exchange": "BINANCE USDⓈ-M",
                "industry": industry,
                "last_price": round(last_price, 4),
                "previous_close": round(previous_close, 4),
                "reference_label": reference_label,
                "change": round(last_price - previous_close, 4),
                "change_pct": round(change_pct, 3),
                "direction": "up" if change_pct > 0 else "down",
                "bar_time_et": as_of.tz_convert(NEW_YORK).strftime("%Y-%m-%d %H:%M ET"),
                "occurred_at_utc": as_of.isoformat(),
                "tradingview_symbol": f"BINANCE:{contract_symbol}.P",
                "source": "Binance USDⓈ-M public API",
            }
        )
    return movers


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
    binance_contracts: dict[str, Symbol] = {}

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
        taiwan_weighted_1h = taiwan_weighted_technical_1h()
    except Exception as exc:
        logging.warning("Taiwan weighted technical refresh failed: %s", exc)
        taiwan_weighted_1h = {
            "available": False,
            "reason": "Taiwan weighted 1-hour technical data is temporarily unavailable",
        }
        errors.append("Taiwan weighted 1-hour technical refresh failed")

    try:
        all_symbols = load_symbols(SYMBOLS_FILE)
        symbols = selected_premarket_symbols(all_symbols)
        frames = download_premarket_frames(symbols)
        binance_contracts = discover_binance_equity_contracts(all_symbols)
        binance_cash_tickers = {stock.ticker for stock in binance_contracts.values()}
        movers = [
            result
            for item in symbols
            if item.ticker not in binance_cash_tickers
            if (result := premarket_mover(item, frames.get(item.ticker, pd.DataFrame()), now, threshold_pct))
            is not None
        ]
        movers.extend(binance_equity_movers(binance_contracts, frames, now, threshold_pct))
    except Exception as exc:
        logging.warning("Pre-market scan failed: %s", exc)
        symbols, frames, movers = [], {}, []
        errors.append("盤前指標股資料暫時無法取得")

    movers.sort(key=lambda item: abs(float(item["change_pct"])), reverse=True)
    selected_movers = movers[:max_movers]
    for mover in selected_movers:
        if mover.get("source") == "Binance USDⓈ-M public API":
            mover["sparkline"] = download_binance_sparkline(str(mover["symbol"]))
    market_open = now.astimezone(NEW_YORK)
    premarket_active = (
        market_open.weekday() < 5 and PREMARKET_OPEN <= market_open.time() < REGULAR_OPEN
    )
    write_payload(
        {
            "updated_at_utc": now.isoformat(),
            "futures": futures,
            "taiwan_weighted_1h": taiwan_weighted_1h,
            "premarket": {
                "active": premarket_active,
                "binance_equity_enabled": bool(binance_contracts),
                "binance_equity_scanned_symbols": len(binance_contracts),
                "threshold_pct": threshold_pct,
                "scanned_symbols": len(frames),
                "movers": selected_movers,
            },
            "source": "Yahoo Finance via yfinance；期貨與盤前報價可能延遲。",
            "errors": errors,
        }
    )
    logging.info(
        "Market pulse refreshed: %s futures, %s Taiwan 1h bars, %s pre-market movers",
        len(futures),
        len(taiwan_weighted_1h.get("bars", [])),
        len(movers),
    )


if __name__ == "__main__":
    main()
