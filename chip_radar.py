#!/usr/bin/env python3
"""Build the source-backed Taiwan institutional Chip Radar.

The radar deliberately separates two ideas that are often mixed together:

* daily foreign-investor / investment-trust flow and its acceleration;
* weekly TDCC shareholder concentration (levels 12--15).

TDCC's public bulk file is a current weekly snapshot.  A change in large-holder
ownership is therefore only calculated after this project has retained at
least two weekly snapshots; it is never fabricated for a historical backtest.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import statistics
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as calendar_date
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from scanner import Symbol, chunks, frame_for_symbol
from sequential import TAIWAN_INDUSTRY_NAMES, fetch_taiwan_industries, fetch_taifex_stock_futures


ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "data" / "chip_radar.json"
HISTORY_FILE = ROOT / "data" / "chip_radar_history.json"
TAIPEI = ZoneInfo("Asia/Taipei")
UTC = timezone.utc

# wwwc is TWSE's current official report host.  The older www host returns a
# CDN 404 from some Python environments even though the report is available.
TWSE_T86_URL = "https://wwwc.twse.com.tw/rwd/zh/fund/T86"
TPEX_INSTITUTIONAL_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
TDCC_DISPERSION_URL = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
TWSE_COMPANY_INFO_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_COMPANY_INFO_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

# This is a bounded, liquid Taiwan equity universe.  It comes from the current
# official TAIFEX underlying list but the site intentionally calls it a
# liquidity watchlist, not a stock-futures list.
DEFAULT_HISTORY_DAYS = 45
HISTORY_BUFFER_DAYS = 18
DEFAULT_TOP_CANDIDATES = 30


def _positive_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _http_text(url: str, timeout: int = 30) -> str:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "KJ-Radar-System/1.0", "Accept": "application/json,text/csv,*/*"},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException as request_error:
        # A few Windows Python builds reject TDCC's otherwise-valid chain with
        # a Subject Key Identifier error.  Curl uses the platform certificate
        # store and still validates HTTPS; it is a safe, no-`-k` fallback.
        curl = shutil.which("curl") or shutil.which("curl.exe")
        if not curl:
            raise request_error
        completed = subprocess.run(
            [
                curl,
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--connect-timeout",
                str(min(timeout, 20)),
                "--max-time",
                str(timeout),
                "--user-agent",
                "KJ-Radar-System/1.0",
                url,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout + 5,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout:
            logging.info("Using platform HTTPS fallback for %s", url.split("?")[0])
            return completed.stdout
        raise request_error


def _http_json(url: str, timeout: int = 30) -> Any:
    return json.loads(_http_text(url, timeout=timeout))


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value).replace(",", "").replace(" ", "").strip())
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _iso_day(value: calendar_date) -> str:
    return value.isoformat()


def load_history() -> dict[str, Any]:
    default: dict[str, Any] = {
        "schema_version": 1,
        "institutional_by_date": {},
        "holder_snapshots": {},
    }
    if not HISTORY_FILE.exists():
        return default
    try:
        payload = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(payload, dict):
        return default
    for key, value in default.items():
        if key not in payload or not isinstance(payload[key], type(value)):
            payload[key] = value
    return payload


def save_history(payload: dict[str, Any], keep_days: int) -> None:
    flows = payload.get("institutional_by_date", {})
    if isinstance(flows, dict):
        ordered = sorted(flows)[-(keep_days + HISTORY_BUFFER_DAYS) :]
        payload["institutional_by_date"] = {day: flows[day] for day in ordered}
    holders = payload.get("holder_snapshots", {})
    if isinstance(holders, dict):
        ordered = sorted(holders)[-14:]
        payload["holder_snapshots"] = {day: holders[day] for day in ordered}
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def recent_weekdays(now: datetime, count: int) -> list[calendar_date]:
    """Return enough weekdays to retain `count` actual market reports."""
    result: list[calendar_date] = []
    cursor = now.astimezone(TAIPEI).date()
    target = count + HISTORY_BUFFER_DAYS
    while len(result) < target:
        if cursor.weekday() < 5:
            result.append(cursor)
        cursor -= timedelta(days=1)
    return result


def fetch_twse_institutional(day: calendar_date, universe: set[str]) -> dict[str, dict[str, int]] | None:
    query = urlencode({"date": day.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"})
    payload = _http_json(f"{TWSE_T86_URL}?{query}")
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return None
    fields = payload.get("fields", [])
    rows = payload.get("data", [])
    if not isinstance(fields, list) or not isinstance(rows, list):
        return None
    field_index = {str(name).strip(): index for index, name in enumerate(fields)}
    code_index = field_index.get("證券代號", 0)
    foreign_index = field_index.get("外陸資買賣超股數(不含外資自營商)", 4)
    trust_index = field_index.get("投信買賣超股數", 10)
    values: dict[str, dict[str, int]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(code_index, foreign_index, trust_index):
            continue
        code = str(row[code_index]).strip()
        if code not in universe:
            continue
        foreign = _as_int(row[foreign_index])
        trust = _as_int(row[trust_index])
        if foreign is None or trust is None:
            continue
        values[code] = {"foreign": foreign, "trust": trust, "venue": "TWSE"}
    return values


def fetch_tpex_latest(universe: set[str]) -> tuple[str | None, dict[str, dict[str, int]]]:
    """Read the official TPEx current day report.

    TPEx's documented OpenAPI endpoint publishes a current report, but does not
    expose a date parameter.  It is used for current cards only; the historical
    event study is explicitly labelled as TWSE-only until a dated TPEx source is
    added.
    """
    try:
        rows = _http_json(TPEX_INSTITUTIONAL_URL)
    except Exception as exc:  # upstream availability should not break the radar
        logging.warning("TPEx institutional source unavailable: %s", exc)
        return None, {}
    if not isinstance(rows, list):
        return None, {}
    values: dict[str, dict[str, int]] = {}
    report_day: str | None = None
    foreign_key = "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference"
    trust_key = "SecuritiesInvestmentTrustCompanies-Difference"
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("SecuritiesCompanyCode") or "").strip()
        if code not in universe:
            continue
        foreign = _as_int(row.get(foreign_key))
        trust = _as_int(row.get(trust_key))
        if foreign is None or trust is None:
            continue
        values[code] = {"foreign": foreign, "trust": trust, "venue": "TPEX"}
        report_day = str(row.get("Date") or report_day or "").strip() or report_day
    return report_day, values


def fetch_tdcc_large_holders(universe: set[str]) -> tuple[str | None, dict[str, float]]:
    """Return TDCC levels 12--15 as a percentage of custody inventory."""
    text = _http_text(TDCC_DISPERSION_URL, timeout=45).lstrip("\ufeff")
    rows = csv.DictReader(StringIO(text))
    result: dict[str, float] = defaultdict(float)
    source_day: str | None = None
    for row in rows:
        code = str(row.get("證券代號") or "").strip()
        if code not in universe:
            continue
        level = _as_int(row.get("持股分級"))
        ratio = _as_float(row.get("占集保庫存數比例%"))
        if level is None or ratio is None:
            continue
        source_day = str(row.get("資料日期") or source_day or "").strip() or source_day
        if 12 <= level <= 15:
            result[code] += ratio
    return source_day, {code: round(value, 4) for code, value in result.items()}


def fetch_industries() -> dict[str, str]:
    """Read industries with a requests/curl fallback for Windows Python."""
    try:
        existing = fetch_taiwan_industries()
    except Exception:
        existing = {}
    if existing:
        return existing
    industries: dict[str, str] = {}
    for source in (TWSE_COMPANY_INFO_URL, TPEX_COMPANY_INFO_URL):
        try:
            rows = _http_json(source)
        except Exception as exc:
            logging.info("Taiwan industry source unavailable: %s", exc)
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("公司代號") or row.get("證券代號") or "").strip()
            raw = str(row.get("產業別") or "").strip()
            if len(code) != 4 or not code.isdigit() or not raw:
                continue
            industries[code] = TAIWAN_INDUSTRY_NAMES.get(raw, raw if not raw.isdigit() else "未分類")
    return industries


def refresh_institutional_history(history: dict[str, Any], now: datetime, universe: set[str], target_days: int) -> None:
    known = history["institutional_by_date"]
    requested = [day for day in recent_weekdays(now, target_days) if _iso_day(day) not in known]
    # The official report has a sizeable payload.  Four concurrent requests
    # finish the initial backfill quickly while staying conservative to TWSE.
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_twse_institutional, day, universe): day for day in requested}
        for future in as_completed(futures):
            day = futures[future]
            try:
                values = future.result()
            except Exception as exc:
                logging.info("TWSE institutional source unavailable for %s: %s", day, exc)
                continue
            if values:
                known[_iso_day(day)] = values


def _download_taiwan_frames(codes: Iterable[str]) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Download daily OHLCV, resolving TWSE first and TPEx as fallback."""
    ordered = sorted(set(codes))
    frames: dict[str, pd.DataFrame] = {}
    venues: dict[str, str] = {}

    def fetch_batch(tickers: list[str]) -> dict[str, pd.DataFrame]:
        downloaded: dict[str, pd.DataFrame] = {}
        for batch in chunks([Symbol(ticker, "") for ticker in tickers], 80):
            tickers_in_batch = [item.ticker for item in batch]
            try:
                response = yf.download(
                    tickers=tickers_in_batch,
                    period="9mo",
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=False,
                    prepost=False,
                    progress=False,
                    threads=True,
                    timeout=35,
                    multi_level_index=True,
                )
            except Exception as exc:
                logging.warning("Taiwan daily price download failed: %s", exc)
                continue
            for ticker in tickers_in_batch:
                frame = frame_for_symbol(response, ticker, len(tickers_in_batch))
                if not {"Open", "Close", "Volume"}.issubset(frame.columns):
                    continue
                clean = frame.copy()
                for column in ("Open", "Close", "Volume"):
                    clean[column] = pd.to_numeric(clean[column], errors="coerce")
                clean = clean.dropna(subset=["Open", "Close", "Volume"]).sort_index()
                if not clean.empty:
                    downloaded[ticker] = clean
        return downloaded

    primary_tickers = [f"{code}.TW" for code in ordered]
    for ticker, frame in fetch_batch(primary_tickers).items():
        code = ticker.removesuffix(".TW")
        frames[code] = frame
        venues[code] = "TWSE"
    fallback_tickers = [f"{code}.TWO" for code in ordered if code not in frames]
    for ticker, frame in fetch_batch(fallback_tickers).items():
        code = ticker.removesuffix(".TWO")
        frames[code] = frame
        venues[code] = "TPEX"
    return frames, venues


def price_records(frame: pd.DataFrame) -> list[dict[str, float | str]]:
    records: list[dict[str, float | str]] = []
    for timestamp, row in frame.iterrows():
        day = pd.Timestamp(timestamp).date().isoformat()
        records.append(
            {
                "date": day,
                "open": float(row["Open"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            }
        )
    return records


def flow_features(flows: list[dict[str, int]], prices: list[dict[str, float | str]]) -> dict[str, float] | None:
    """Calculate point-in-time features; inputs must end on the signal day."""
    if len(flows) < 10 or len(prices) < 22:
        return None
    last_five = flows[-5:]
    prior_five = flows[-10:-5]
    latest_prices = prices[-20:]
    average_volume = statistics.fmean(float(item["volume"]) for item in latest_prices)
    if average_volume <= 0:
        return None
    foreign_5 = sum(int(item["foreign"]) for item in last_five)
    trust_5 = sum(int(item["trust"]) for item in last_five)
    previous_net_5 = sum(int(item["foreign"]) + int(item["trust"]) for item in prior_five)
    net_5 = foreign_5 + trust_5
    close = float(prices[-1]["close"])
    previous_close = float(prices[-2]["close"])
    ma20 = statistics.fmean(float(item["close"]) for item in latest_prices)
    latest_volume = float(prices[-1]["volume"])
    return {
        "foreign_5": float(foreign_5),
        "trust_5": float(trust_5),
        "foreign_positive_days": float(sum(int(item["foreign"]) > 0 for item in last_five)),
        "trust_positive_days": float(sum(int(item["trust"]) > 0 for item in last_five)),
        "flow_ratio": net_5 / average_volume,
        "acceleration_ratio": (net_5 - previous_net_5) / average_volume,
        "close": close,
        "previous_close": previous_close,
        "ma20": ma20,
        "volume_ratio": latest_volume / average_volume,
    }


def score_features(features: dict[str, float], holder_delta_pct: float | None) -> tuple[float, dict[str, float]]:
    foreign_score = _clamp(features["foreign_5"] / max(1, abs(features["foreign_5"]) + abs(features["trust_5"])) * 30, 0, 30)
    # Flow ratio is a better magnitude measure than absolute shares across stocks.
    flow_score = _clamp(features["flow_ratio"] * 600, 0, 30)
    trust_score = _clamp(features["trust_5"] / max(1, abs(features["foreign_5"]) + abs(features["trust_5"])) * 20, 0, 20)
    persistence_score = _clamp((features["foreign_positive_days"] + features["trust_positive_days"] - 4) * 2.5, 0, 10)
    acceleration_score = _clamp(features["acceleration_ratio"] * 420, 0, 10)
    confirmation_score = (5 if features["close"] >= features["ma20"] else 0) + (5 if features["volume_ratio"] >= 1 else 0)
    holder_change_score = _clamp((holder_delta_pct or 0.0) * 4, 0, 10)
    # foreign_score is intentionally capped and is not a share-of-score proxy;
    # flow_score carries the actual relative-size information.
    components = {
        "foreign_flow": round((foreign_score + flow_score) * 0.5, 1),
        "trust_flow": round(trust_score, 1),
        "persistence": round(persistence_score, 1),
        "acceleration": round(acceleration_score, 1),
        "price_volume": round(confirmation_score, 1),
        "holder_weekly_change": round(holder_change_score, 1),
    }
    total = round(sum(components.values()), 1)
    return total, components


def qualifies(features: dict[str, float], score: float) -> bool:
    return bool(
        score >= 48
        and features["foreign_5"] > 0
        and features["trust_5"] > 0
        and features["foreign_positive_days"] >= 3
        and features["close"] >= features["ma20"]
    )


def holder_delta(history: dict[str, Any], latest_day: str | None, code: str) -> float | None:
    snapshots = history.get("holder_snapshots", {})
    if not latest_day or not isinstance(snapshots, dict):
        return None
    older = [day for day in sorted(snapshots) if day < latest_day]
    if not older:
        return None
    current = _as_float((snapshots.get(latest_day) or {}).get(code))
    previous = _as_float((snapshots.get(older[-1]) or {}).get(code))
    if current is None or previous is None:
        return None
    return round(current - previous, 3)


def make_candidate(
    code: str,
    name: str,
    industry: str | None,
    venue: str,
    prices: list[dict[str, float | str]],
    flows: list[dict[str, int]],
    holder_pct: float | None,
    holder_change: float | None,
) -> dict[str, Any] | None:
    features = flow_features(flows, prices)
    if features is None:
        return None
    score, components = score_features(features, holder_change)
    today_change = ((features["close"] / features["previous_close"]) - 1) * 100 if features["previous_close"] else 0.0
    return {
        "symbol": code,
        "name": name,
        "industry": industry or "未分類",
        "exchange": venue,
        "market": "台股",
        "tradingview_symbol": f"{'TWSE' if venue == 'TWSE' else 'TPEX'}:{code}",
        "last_price": round(features["close"], 2),
        "today_change_pct": round(today_change, 2),
        "score": score,
        "qualified": qualifies(features, score),
        "foreign_5_shares": int(features["foreign_5"]),
        "trust_5_shares": int(features["trust_5"]),
        "foreign_positive_days": int(features["foreign_positive_days"]),
        "trust_positive_days": int(features["trust_positive_days"]),
        "flow_ratio_pct": round(features["flow_ratio"] * 100, 3),
        "acceleration_ratio_pct": round(features["acceleration_ratio"] * 100, 3),
        "volume_ratio": round(features["volume_ratio"], 2),
        "above_ma20": bool(features["close"] >= features["ma20"]),
        "large_holder_pct": round(holder_pct, 2) if holder_pct is not None else None,
        "large_holder_weekly_change_pct": holder_change,
        "score_components": components,
        "sparkline": [round(float(item["close"]), 2) for item in prices[-30:]],
    }


def backtest_flow_model(
    flows_by_date: dict[str, dict[str, dict[str, int]]],
    prices_by_code: dict[str, list[dict[str, float | str]]],
) -> dict[str, Any]:
    """Run a transparent next-open to fifth-close event study for TWSE flow data.

    This intentionally omits TDCC holder *changes* because the public bulk
    endpoint provides the current weekly snapshot; the project must collect a
    second snapshot before that variable can be tested without look-ahead.
    """
    dates = sorted(flows_by_date)
    returns: list[float] = []
    sampled_days = 0
    for index in range(10, max(10, len(dates) - 6)):
        signal_day = dates[index]
        trailing_days = dates[: index + 1]
        daily_candidates: list[tuple[str, float]] = []
        for code, records in prices_by_code.items():
            daily_flows = [flows_by_date[day][code] for day in trailing_days if code in flows_by_date[day]]
            price_window = [record for record in records if str(record["date"]) <= signal_day]
            features = flow_features(daily_flows, price_window)
            if features is None:
                continue
            score, _ = score_features(features, None)
            if qualifies(features, score):
                daily_candidates.append((code, score))
        if not daily_candidates:
            continue
        sampled_days += 1
        # Cross-sectional cap prevents a single active day from dominating the study.
        for code, _ in sorted(daily_candidates, key=lambda item: item[1], reverse=True)[:12]:
            records = prices_by_code[code]
            matching = next((position for position, row in enumerate(records) if row["date"] == signal_day), None)
            if matching is None or matching + 5 >= len(records):
                continue
            entry = float(records[matching + 1]["open"])
            exit_price = float(records[matching + 5]["close"])
            if entry > 0:
                returns.append((exit_price / entry - 1) * 100)
    complete = len(dates) >= 30 and len(returns) >= 20
    if not returns:
        return {
            "ready": False,
            "reason": "法人歷史與後續 5 個交易日價格尚不足，資料累積後會自動產生回測。",
            "model_scope": "上市股票的外資／投信流動模型；不含大戶週增減。",
            "available_sessions": len(dates),
        }
    positive = [value for value in returns if value > 0]
    negative = [value for value in returns if value <= 0]
    return {
        "ready": complete,
        "model_scope": "上市股票的外資／投信流動模型；訊號日收盤後，以下一交易日開盤進場、第五個交易日收盤出場；不含大戶週增減。",
        "period_start": dates[0] if dates else None,
        "period_end": dates[-1] if dates else None,
        "available_sessions": len(dates),
        "sample_days": sampled_days,
        "signals": len(returns),
        "win_rate_pct": round(len(positive) / len(returns) * 100, 1),
        "average_return_5d_pct": round(statistics.fmean(returns), 2),
        "median_return_5d_pct": round(statistics.median(returns), 2),
        "average_win_pct": round(statistics.fmean(positive), 2) if positive else None,
        "average_loss_pct": round(statistics.fmean(negative), 2) if negative else None,
        "caveat": "樣本採目前流動性觀察名單，存在存活者偏誤；此為研究事件分析，不是績效保證或投資建議。",
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(UTC)
    history_days = _positive_int_env("CHIP_RADAR_HISTORY_DAYS", DEFAULT_HISTORY_DAYS, 25, 90)
    top_candidates = _positive_int_env("CHIP_RADAR_TOP_CANDIDATES", DEFAULT_TOP_CANDIDATES, 10, 60)
    history = load_history()

    try:
        universe_map = fetch_taifex_stock_futures()
    except Exception as exc:
        raise RuntimeError(f"台股流動性名單來源無法取得：{exc}") from exc
    universe = set(universe_map)
    industries = fetch_industries()
    refresh_institutional_history(history, now, universe, history_days)

    tdcc_day: str | None = None
    holder_values: dict[str, float] = {}
    try:
        tdcc_day, holder_values = fetch_tdcc_large_holders(universe)
        if tdcc_day and holder_values:
            history["holder_snapshots"][tdcc_day] = holder_values
    except Exception as exc:
        logging.warning("TDCC large-holder source unavailable: %s", exc)

    tpex_day, tpex_latest = fetch_tpex_latest(universe)
    latest_by_date = history["institutional_by_date"]
    sorted_days = sorted(latest_by_date)
    latest_day = sorted_days[-1] if sorted_days else None
    latest_twse = latest_by_date.get(latest_day, {}) if latest_day else {}
    frames, venues = _download_taiwan_frames(universe)
    prices_by_code = {code: price_records(frame) for code, frame in frames.items()}

    candidates: list[dict[str, Any]] = []
    for code, records in prices_by_code.items():
        venue = venues.get(code, "TWSE")
        if venue == "TPEX":
            # TPEx's documented endpoint is current-only.  Retain it in the
            # current view, but require at least ten observations before it can
            # receive a flow score.
            flow_rows: list[dict[str, int]] = []
            if code in tpex_latest:
                flow_rows.append(tpex_latest[code])
        else:
            flow_rows = [latest_by_date[day][code] for day in sorted_days if code in latest_by_date[day]]
        item = make_candidate(
            code,
            universe_map.get(code, code),
            industries.get(code),
            venue,
            records,
            flow_rows,
            holder_values.get(code),
            holder_delta(history, tdcc_day, code),
        )
        if item is not None:
            candidates.append(item)
    candidates.sort(key=lambda item: (not bool(item["qualified"]), -float(item["score"]), -float(item["flow_ratio_pct"])))
    displayed = candidates[:top_candidates]
    qualified_count = sum(bool(item["qualified"]) for item in candidates)

    backtest_flows = {
        day: {code: value for code, value in values.items() if value.get("venue") == "TWSE"}
        for day, values in latest_by_date.items()
    }
    backtest = backtest_flow_model(backtest_flows, prices_by_code)
    save_history(history, history_days)

    output = {
        "schema_version": 1,
        "updated_at_utc": now.isoformat(),
        "data_as_of": latest_day,
        "universe_label": "台股流動性觀察名單",
        "universe_count": len(universe),
        "priced_symbols": len(prices_by_code),
        "qualified_candidates": qualified_count,
        "candidates": displayed,
        "backtest": backtest,
        "holder_snapshot": {
            "as_of": tdcc_day,
            "available": bool(tdcc_day and holder_values),
            "definition": "TDCC 持股分級 12–15 的集保庫存比例合計；第二週起才計算週增減。",
        },
        "source": "法人：TWSE 三大法人買賣超日報、TPEx 三大法人買賣明細；大戶：TDCC 集保戶股權分散表；價格與成交量：Yahoo Finance via yfinance。",
        "methodology": "候選分數由外資／投信近 5 日流入、流入連續性、相對成交量的流入強度、5 日加速、價格／量能確認及（有第二週快照後）大戶持股週增減組成。大戶集中度本身不被視為加碼訊號。",
        "caveat": "僅供研究與監測；法人買賣與大戶持股不能單獨推論未來報酬。",
        "tpex_current_report_as_of": tpex_day,
    }
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    logging.info(
        "Chip radar refreshed: %s priced symbols, %s qualified candidates, %s historical sessions",
        len(prices_by_code),
        qualified_count,
        len(sorted_days),
    )


if __name__ == "__main__":
    main()
