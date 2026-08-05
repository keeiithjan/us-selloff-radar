#!/usr/bin/env python3
"""產生 GitHub Pages 網頁使用的美股爆量急跌警示資料。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "data" / "alerts.json"
SYMBOLS_FILE = ROOT / "symbols.csv"
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Settings:
    bar_minutes: int = 5
    price_window_bars: int = 6
    min_price_drop_pct: float = 3.0
    volume_baseline_bars: int = 20
    min_volume_multiple: float = 3.0
    min_price_usd: float = 5.0
    min_avg_daily_dollar_volume: float = 20_000_000
    min_bar_dollar_volume: float = 250_000
    max_symbols_per_request: int = 100

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            min_price_drop_pct=_float_env("MIN_PRICE_DROP_PCT", 3.0),
            min_volume_multiple=_float_env("MIN_VOLUME_MULTIPLE", 3.0),
            min_price_usd=_float_env("MIN_PRICE_USD", 5.0),
            min_avg_daily_dollar_volume=_float_env(
                "MIN_AVG_DAILY_DOLLAR_VOLUME", 20_000_000
            ),
            min_bar_dollar_volume=_float_env("MIN_BAR_DOLLAR_VOLUME", 250_000),
            max_symbols_per_request=_int_env("MAX_SYMBOLS_PER_REQUEST", 100),
        )


@dataclass(frozen=True)
class Symbol:
    ticker: str
    exchange: str
    industry: str = ""


@dataclass(frozen=True)
class Alert:
    symbol: str
    exchange: str
    industry: str
    bar_time_et: str
    last_price: float
    price_change_pct: float
    latest_bar_volume: int
    baseline_bar_volume: int
    volume_multiple: float
    average_daily_dollar_volume: float
    latest_bar_dollar_volume: float
    severity_score: float


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必須是數字。") from exc


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必須是整數。") from exc


def is_regular_session(now: datetime) -> bool:
    """僅在美東平日一般盤運算，休市日則不會有可用最新 K 線。"""
    local_now = now.astimezone(NEW_YORK)
    return (
        local_now.weekday() < 5
        and clock_time(9, 30) <= local_now.time() < clock_time(16, 0)
    )


def load_symbols(path: Path) -> list[Symbol]:
    raw = pd.read_csv(path, dtype=str)
    columns = {name.strip().lower(): name for name in raw.columns}
    if "symbol" not in columns:
        raise ValueError("symbols.csv 必須含有 symbol 欄位。")
    exchange_column = columns.get("exchange")
    industry_column = columns.get("industry")

    results: list[Symbol] = []
    seen: set[str] = set()
    for _, row in raw.iterrows():
        ticker = str(row[columns["symbol"]]).strip().upper().replace(".", "-")
        exchange = (
            str(row[exchange_column]).strip().upper()
            if exchange_column and pd.notna(row[exchange_column])
            else "NASDAQ"
        )
        industry = (
            str(row[industry_column]).strip()
            if industry_column and pd.notna(row[industry_column])
            else ""
        )
        if ticker and ticker not in seen:
            results.append(Symbol(ticker=ticker, exchange=exchange, industry=industry))
            seen.add(ticker)
    if not results:
        raise ValueError("symbols.csv 沒有可用的標的。")
    return results


def chunks(items: list[Symbol], size: int) -> Iterable[list[Symbol]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def frame_for_symbol(
    download: pd.DataFrame, ticker: str, batch_size: int
) -> pd.DataFrame:
    if download.empty:
        return pd.DataFrame()
    if not isinstance(download.columns, pd.MultiIndex):
        return download.copy() if batch_size == 1 else pd.DataFrame()

    first_level = download.columns.get_level_values(0)
    second_level = download.columns.get_level_values(1)
    if ticker in first_level:
        return download[ticker].copy()
    if ticker in second_level:
        return download.xs(ticker, axis=1, level=1).copy()
    return pd.DataFrame()


def download_bars(symbols: list[Symbol], settings: Settings) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for batch in chunks(symbols, settings.max_symbols_per_request):
        tickers = [item.ticker for item in batch]
        try:
            response = yf.download(
                tickers=tickers,
                period="5d",
                interval="5m",
                group_by="ticker",
                auto_adjust=False,
                prepost=False,
                progress=False,
                threads=True,
                timeout=30,
                multi_level_index=True,
            )
        except Exception as exc:
            logging.warning("下載一批資料失敗：%s", exc)
            continue

        for ticker in tickers:
            frame = frame_for_symbol(response, ticker, len(tickers))
            if {"Close", "Volume"}.issubset(frame.columns):
                frames[ticker] = frame.dropna(subset=["Close", "Volume"]).copy()
    return frames


def session_bars(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    index = pd.DatetimeIndex(frame.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    session = frame.copy()
    session.index = index.tz_convert(NEW_YORK)
    mask = (session.index.time >= clock_time(9, 30)) & (
        session.index.time < clock_time(16, 0)
    )
    return session.loc[mask]


def average_daily_dollar_volume(frame: pd.DataFrame) -> float:
    profile = frame[["Close", "Volume"]].copy()
    profile["session_date"] = profile.index.date
    daily = profile.groupby("session_date", sort=True).agg(
        close=("Close", "last"),
        volume=("Volume", "sum"),
    )
    if len(daily) < 2:
        return 0.0
    completed_days = daily.iloc[:-1]
    return float((completed_days["close"] * completed_days["volume"]).mean())


def detect_alert(
    symbol: Symbol, raw_frame: pd.DataFrame, settings: Settings, now: datetime
) -> Alert | None:
    frame = session_bars(raw_frame)
    required_bars = max(
        settings.price_window_bars + 1, settings.volume_baseline_bars + 1
    )
    if len(frame) < required_bars:
        return None

    last_bar_time = frame.index[-1].to_pydatetime()
    if now.astimezone(NEW_YORK) - last_bar_time > timedelta(minutes=30):
        return None

    close = pd.to_numeric(frame["Close"], errors="coerce")
    volume = pd.to_numeric(frame["Volume"], errors="coerce")
    latest_price = float(close.iloc[-1])
    prior_price = float(close.iloc[-(settings.price_window_bars + 1)])
    baseline = float(
        volume.iloc[-(settings.volume_baseline_bars + 1) : -1].median()
    )
    latest_volume = float(volume.iloc[-1])
    if prior_price <= 0 or baseline <= 0:
        return None

    price_change_pct = (latest_price / prior_price - 1) * 100
    volume_multiple = latest_volume / baseline
    average_dollar_volume = average_daily_dollar_volume(frame)
    bar_dollar_volume = latest_price * latest_volume

    passed = (
        latest_price >= settings.min_price_usd
        and price_change_pct <= -settings.min_price_drop_pct
        and volume_multiple >= settings.min_volume_multiple
        and average_dollar_volume >= settings.min_avg_daily_dollar_volume
        and bar_dollar_volume >= settings.min_bar_dollar_volume
    )
    if not passed:
        return None

    return Alert(
        symbol=symbol.ticker,
        exchange=symbol.exchange,
        industry=symbol.industry,
        bar_time_et=last_bar_time.strftime("%Y-%m-%d %H:%M ET"),
        last_price=round(latest_price, 2),
        price_change_pct=round(price_change_pct, 2),
        latest_bar_volume=int(latest_volume),
        baseline_bar_volume=int(baseline),
        volume_multiple=round(volume_multiple, 2),
        average_daily_dollar_volume=round(average_dollar_volume, 2),
        latest_bar_dollar_volume=round(bar_dollar_volume, 2),
        severity_score=round(abs(price_change_pct) * volume_multiple, 2),
    )


def write_payload(alerts: list[Alert], market_status: str, scanned_symbols: int) -> None:
    payload = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "market_status": market_status,
        "scanned_symbols": scanned_symbols,
        "source": "Yahoo Finance via yfinance; research/monitoring only, not an executable quote.",
        "alerts": [asdict(alert) for alert in alerts],
    }
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.from_env()
    if settings.max_symbols_per_request < 1:
        raise ValueError("MAX_SYMBOLS_PER_REQUEST 必須至少為 1。")
    symbols = load_symbols(SYMBOLS_FILE)
    now = datetime.now(NEW_YORK)

    if not is_regular_session(now):
        write_payload([], "closed", 0)
        logging.info("目前不在美股一般盤時段；已更新休市狀態。")
        return

    frames = download_bars(symbols, settings)
    lookup = {item.ticker: item for item in symbols}
    alerts = [
        alert
        for ticker, frame in frames.items()
        if (alert := detect_alert(lookup[ticker], frame, settings, now)) is not None
    ]
    alerts.sort(key=lambda item: item.severity_score, reverse=True)
    write_payload(alerts, "open", len(frames))
    logging.info("掃描 %d/%d 標的，產生 %d 筆警示。", len(frames), len(symbols), len(alerts))


if __name__ == "__main__":
    main()
