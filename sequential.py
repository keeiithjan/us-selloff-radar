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
TRADINGVIEW_EXPORT_FILE = ROOT / "data" / "KJ-Radar-TradingView.TXT"
WEEKLY_RECLAIM_EXPORT_FILE = ROOT / "data" / "KJ-Radar-Weekly-White-Reclaim.TXT"
TAIWAN_PINE_SCREENER_FILE = ROOT / "data" / "KJ-Taiwan-Pine-Screener-Universe.TXT"
BINANCE_CRYPTO_PERPETUALS_FILE = ROOT / "data" / "KJ-Binance-Crypto-Perpetuals.TXT"
BINANCE_STOCK_PERPETUALS_FILE = ROOT / "data" / "KJ-Binance-Stock-Perpetuals.TXT"
PEPPERSTONE_CFD_FILE = ROOT / "data" / "KJ-Pepperstone-Liquid-CFDs.TXT"
SYMBOLS_FILE = ROOT / "symbols.csv"
TAIPEI = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
TAIFEX_STOCK_FUTURES_URL = "https://www.taifex.com.tw/cht/5/stockMargining"
BINANCE_DATA_URL = "https://data-api.binance.vision/api/v3"
BINANCE_FUTURES_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
BINANCE_FUTURES_DATA_URL = "https://fapi.binance.com/fapi/v1"
TWSE_COMPANY_INFO_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_COMPANY_INFO_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

# Binance's TradFi tab lists perpetual contracts that track these individual
# equities. Keep stocks separate from ETFs, indices, commodities, and crypto so
# this file is a clean TradingView universe for the requested stock-perp scan.
# Source: Binance Academy's April 2026 TradFi contracts overview.
BINANCE_STOCK_PERPETUALS = (
    "MSTR", "COIN", "HOOD", "CRCL", "PAYP",
    "TSLA", "AMZN", "META", "GOOGL", "AAPL", "MSFT",
    "NVDA", "MU", "SNDK", "TSM", "AVGO", "INTC",
    "PLTR", "BABA",
)

# TWSE / TPEx publish two-digit industry codes in their company datasets.
# Convert them before writing JSON so users see a meaningful sector, not "24".
TAIWAN_INDUSTRY_NAMES = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "07": "化學工業", "08": "玻璃陶瓷",
    "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業",
    "13": "電子工業", "14": "建材營造", "15": "航運業", "16": "觀光餐旅",
    "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他",
    "21": "化學工業", "22": "生技醫療業", "23": "油電燃氣業", "24": "半導體業",
    "25": "電腦及週邊設備業", "26": "光電業", "27": "通信網路業", "28": "電子零組件業",
    "29": "電子通路業", "30": "資訊服務業", "31": "其他電子業", "32": "文化創意業",
    "33": "農業科技業", "34": "電子商務業", "35": "綠能環保業", "36": "數位雲端業",
    "37": "運動休閒業", "38": "居家生活業",
}

# Taiwan exchange classifications describe an industry, not the product that
# drives a signal.  Keep a focused product taxonomy for the actively monitored
# names so cards can distinguish, for example, CPO from ABF substrates instead
# of placing both under the broad "電子零組件業" label.  Unmapped names remain
# explicitly marked rather than being assigned a speculative product.
TAIWAN_PRODUCT_CATEGORIES = {
    # Foundry, memory, IC design and packaging
    "2330": "先進製程晶圓代工", "2303": "成熟製程晶圓代工", "5347": "特殊製程晶圓代工",
    "6770": "成熟製程晶圓代工", "2408": "DRAM 記憶體", "2344": "利基型記憶體",
    "2337": "快閃記憶體", "2454": "手機／邊緣 AI SoC", "3034": "顯示驅動 IC",
    "3443": "特殊應用 IC（ASIC）", "3661": "AI／高速運算 ASIC", "5269": "特殊應用 IC（ASIC）",
    "3529": "矽智財／嵌入式記憶體", "6531": "利基記憶體 IC", "2379": "網通／音訊 IC",
    "3035": "IC 設計服務", "3711": "先進封裝／測試", "6239": "記憶體封裝測試",
    "2449": "半導體測試", "3264": "功率半導體", "6415": "電源管理 IC",
    # CPO / optical communications
    "3163": "CPO／矽光子光通訊", "3363": "CPO／矽光子光通訊", "4979": "CPO／矽光子光通訊",
    "6442": "CPO／矽光子光通訊", "3081": "高速光收發模組", "4908": "高速光收發模組",
    "3450": "高速光收發模組", "3362": "光學鏡頭／光通訊元件", "4971": "磊晶／光電材料",
    # ABF, PCB and materials
    "3037": "ABF 載板", "3189": "ABF 載板", "8046": "ABF 載板／高階 PCB",
    "2368": "高階伺服器 PCB", "3044": "高階 PCB", "2313": "HDI／軟硬板 PCB",
    "4958": "高階 PCB／IC 載板", "2383": "銅箔基板（CCL）", "6274": "銅箔基板（CCL）",
    "6278": "銅箔基板（CCL）", "6269": "軟板／手機 PCB", "8155": "PCB 鑽針／耗材",
    # AI servers, power and networking
    "2382": "AI 伺服器 ODM", "3231": "AI 伺服器 ODM", "2356": "AI 伺服器 ODM",
    "6669": "雲端 AI 伺服器", "2324": "筆電／伺服器 ODM", "4938": "消費電子 ODM",
    "2376": "伺服器／主機板", "2377": "電競／主機板", "2353": "筆電／顯示器",
    "2308": "資料中心電源／散熱", "2301": "電源供應器／光電", "3017": "網通／顯示器",
    "2345": "網通設備", "5388": "網通交換器", "2344": "利基型記憶體",
    # Components, displays and storage
    "2327": "被動元件", "2492": "被動元件", "2375": "被動元件", "2498": "被動元件",
    "3008": "高階手機鏡頭", "3406": "手機鏡頭／光學元件", "3481": "面板模組",
    "2409": "面板", "3481": "面板模組", "2354": "觸控面板", "3702": "手機鏡頭／感測模組",
    "2371": "硬碟／資料儲存", "2352": "記憶體模組", "2347": "IT 通路／企業設備",
    # EV, industrial and healthcare
    "1519": "車用馬達／電動車零組件", "1522": "汽車零組件", "2201": "汽車整車",
    "2395": "車用電子／網通", "3552": "ADAS／車用電子", "1536": "工具機／自動化",
    "2049": "上銀精密傳動／自動化", "1590": "精密機械／自動化", "4137": "生技新藥",
    "6472": "生技醫療通路", "4743": "醫療耗材",
    # Flexible materials and specialty CCL
    "8039": "軟性銅箔基板（FCCL）／FPC 材料",
}

# When a Taiwan name is not in the carefully maintained map above, its product
# label is inferred from the public company business description returned by
# Yahoo Finance.  These rules intentionally use concrete product vocabulary;
# no match falls back to the exchange's industry instead of inventing a theme.
TAIWAN_BUSINESS_PRODUCT_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("flexible copper-clad", "fccl", "coverlay", "bonding sheet", "fpc material"), "軟性銅箔基板（FCCL）／FPC 材料"),
    (("abf", "ic carrier", "fcbga", "fc-csp", "package substrate"), "IC 載板／ABF 載板"),
    (("co-packaged optics", "silicon photonic", "optical transceiver", "optical module"), "CPO／矽光子／高速光通訊"),
    (("printed circuit board", "pcb", "hdi", "rigid-flex"), "PCB／HDI／軟硬板"),
    (("wafer foundry", "wafer fabrication", "semiconductor manufacturing"), "半導體晶圓製造"),
    (("integrated circuit design", "ic design", "system-on-chip", "soc"), "IC 設計／系統單晶片"),
    (("semiconductor testing", "burn-in", "semiconductor packaging"), "半導體封裝測試"),
    (("server", "data center", "motherboard"), "伺服器／資料中心硬體"),
    (("power supply", "power conversion", "thermal solution", "cooling"), "電源供應／散熱"),
    (("network switch", "network equipment", "wireless communication"), "網通設備／交換器"),
    (("memory module", "dram", "flash memory", "nand"), "記憶體／記憶體模組"),
    (("display panel", "lcd panel", "oled panel"), "面板／顯示器"),
    (("camera lens", "optical lens", "image sensor"), "光學鏡頭／影像感測"),
    (("passive component", "capacitor", "inductor", "resistor"), "被動元件"),
    (("electric vehicle", "automotive electronics", "automotive component"), "車用電子／電動車零組件"),
    (("medical device", "medical equipment", "pharmaceutical", "biotechnology"), "醫療器材／生技製藥"),
)


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

# This monitor deliberately keeps the current, still-forming week.  The user
# wants the week's opening position and an intraweek drop/reclaim to count
# before Friday's close, so it is collected outside the confirmed-TD frames.
WEEKLY_RECLAIM_TIMEFRAME = Timeframe("1w", "週線", "1wk", "10y", "W", None)
WEEKLY_WHITE_LENGTH = 50
WEEKLY_RECLAIM_LOOKBACK_WEEKS = 3
WEEKLY_RECLAIM_VISIBLE_WEEKS = 2
WEEKLY_OPEN_CLOSE_BONUS = 12
WEEKLY_SECOND_WEEK_NEAR_WHITE_PCT = 1.5
WEEKLY_SECOND_WEEK_NEAR_WHITE_BONUS = 8
HOURLY_WHITE_ABOVE_BONUS = 15
HOURLY_SECOND_RECLAIM_BONUS = 35
HOURLY_SECOND_RECLAIM_RECENCY_BARS = 4

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
FX_SESSION = MarketSession(UTC)


@dataclass(frozen=True)
class Instrument:
    ticker: str
    symbol: str
    exchange: str
    market: str
    session: MarketSession
    name: str | None = None
    industry: str | None = None


# Pepperstone has no centralised CFD-volume feed.  This compact pool therefore
# uses the most liquid underlying futures or cash-index proxy available from
# Yahoo Finance for calculations, while keeping the matching Pepperstone
# TradingView symbol for chart navigation.  It deliberately excludes long-tail
# FX crosses: only metals, energy, headline equity indices and core FX pairs
# remain.  Tuple fields: Yahoo proxy, Pepperstone chart symbol, Chinese name,
# product-led category.
PEPPERSTONE_CFD_SPECS: tuple[tuple[str, str, str, str], ...] = (
    # Precious metals and energy
    ("GC=F", "XAUUSD", "黃金現貨 CFD", "貴金屬｜黃金"),
    ("SI=F", "XAGUSD", "白銀現貨 CFD", "貴金屬｜白銀"),
    ("CL=F", "SPOTCRUDE", "美國原油 CFD", "能源｜美國原油（WTI）"),
    ("BZ=F", "SPOTBRENT", "布蘭特原油 CFD", "能源｜布蘭特原油"),
    # Liquid global equity-index benchmarks
    ("ES=F", "US500", "S&P 500 CFD", "股價指數｜美國大型股（S&P 500）"),
    ("NQ=F", "NAS100", "NASDAQ 100 CFD", "股價指數｜美國科技（NASDAQ 100）"),
    ("YM=F", "US30", "道瓊工業指數 CFD", "股價指數｜美國藍籌（Dow 30）"),
    ("RTY=F", "US2000", "Russell 2000 CFD", "股價指數｜美國小型股（Russell 2000）"),
    ("NKD=F", "JPN225", "日經 225 CFD", "股價指數｜日本（日經 225）"),
    ("^GDAXI", "GER40", "德國 40 CFD", "股價指數｜德國大型股（DAX 40）"),
    # Core, high-turnover currency pairs only
    ("EURUSD=X", "EURUSD", "歐元／美元", "主要外匯｜EUR/USD"),
    ("JPY=X", "USDJPY", "美元／日圓", "主要外匯｜USD/JPY"),
    ("GBPUSD=X", "GBPUSD", "英鎊／美元", "主要外匯｜GBP/USD"),
    ("AUDUSD=X", "AUDUSD", "澳幣／美元", "主要外匯｜AUD/USD"),
    ("CAD=X", "USDCAD", "美元／加幣", "主要外匯｜USD/CAD"),
    ("CHF=X", "USDCHF", "美元／瑞郎", "主要外匯｜USD/CHF"),
    ("NZDUSD=X", "NZDUSD", "紐元／美元", "主要外匯｜NZD/USD"),
    ("EURJPY=X", "EURJPY", "歐元／日圓", "主要外匯｜EUR/JPY"),
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
            code = str(
                row.get("公司代號")
                or row.get("證券代號")
                or row.get("SecuritiesCompanyCode")
                or ""
            ).strip().upper()
            raw_industry = str(
                row.get("產業別") or row.get("SecuritiesIndustryCode") or ""
            ).strip()
            industry = TAIWAN_INDUSTRY_NAMES.get(raw_industry, raw_industry)
            if re.fullmatch(r"\d{1,2}", raw_industry) and raw_industry not in TAIWAN_INDUSTRY_NAMES:
                industry = "未分類"
            if re.fullmatch(r"\d{4,6}[A-Z]?", code) and industry:
                industries[code] = industry
    return industries


def _classify_taiwan_business_description(description: object) -> str | None:
    """Map a public business description to a concrete product class."""
    text = str(description or "").lower()
    if not text:
        return None
    for keywords, category in TAIWAN_BUSINESS_PRODUCT_RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return None


def product_category_for(
    instrument: Instrument, public_profile_cache: dict[str, str | None] | None = None
) -> str:
    """Return a concise, product-led label for UI cards and exports."""
    if instrument.market == "台股":
        category = TAIWAN_PRODUCT_CATEGORIES.get(instrument.symbol)
        if category:
            return category
        cache = public_profile_cache if public_profile_cache is not None else {}
        if instrument.ticker not in cache:
            try:
                profile = yf.Ticker(instrument.ticker).get_info()
                cache[instrument.ticker] = _classify_taiwan_business_description(
                    profile.get("longBusinessSummary") if isinstance(profile, dict) else None
                )
            except Exception as exc:
                logging.info("%s 公司業務描述讀取失敗：%s", instrument.symbol, exc)
                cache[instrument.ticker] = None
        if cache[instrument.ticker]:
            return str(cache[instrument.ticker])
        if instrument.industry:
            return f"產業分類：{instrument.industry}"
        return "產業分類：交易所未提供"
    if instrument.market == "幣安 USDT 永續":
        return "加密資產／USDT 永續"
    if instrument.market == "Pepperstone CFD":
        return instrument.industry or "Pepperstone 高流動性 CFD"
    return instrument.industry or "產業分類：交易所未提供"


def tradingview_symbol_for(instrument: Instrument) -> str:
    """Return the TradingView ticker, including .P for Binance perpetuals."""
    ticker = instrument.symbol
    if instrument.market == "幣安 USDT 永續":
        ticker = f"{ticker}.P"
    return f"{instrument.exchange}:{ticker}"


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


def fetch_pepperstone_instruments() -> list[Instrument]:
    """Return the compact Pepperstone liquid-CFD monitoring pool."""
    return [
        Instrument(
            ticker,
            symbol,
            "PEPPERSTONE",
            "Pepperstone CFD",
            FX_SESSION,
            name,
            category,
        )
        for ticker, symbol, name, category in PEPPERSTONE_CFD_SPECS
    ]


def fetch_binance_instruments() -> list[Instrument]:
    """Select the most liquid live Binance USDⓈ-M USDT crypto perpetuals.

    The export file intentionally contains every valid contract.  Monitoring is
    capped at a liquid, predictable pool (default 200), ranked by Binance's
    rolling 24-hour USDT notional volume.  This avoids consuming Actions time
    on inactive long-tail contracts while monitoring the pairs most relevant to
    the Radar.
    """
    configured = int(os.getenv("BINANCE_FUTURES_TOP_USDT_PERPETUALS", "200"))
    if configured < 1 or configured > 250:
        raise ValueError("BINANCE_FUTURES_TOP_USDT_PERPETUALS 必須介於 1 到 250")

    stable_bases = {
        "USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "GUSD", "LUSD",
        "FRAX", "USDD", "USDE", "USDS", "USD1", "PYUSD", "RLUSD", "DUSD",
    }

    info = _http_json_url(BINANCE_FUTURES_INFO_URL)
    contracts = info.get("symbols", []) if isinstance(info, dict) else []
    active: set[str] = set()
    for contract in contracts if isinstance(contracts, list) else []:
        if not isinstance(contract, dict):
            continue
        symbol = str(contract.get("symbol", "")).upper()
        if (
            contract.get("status") == "TRADING"
            and contract.get("contractType") == "PERPETUAL"
            and contract.get("quoteAsset") == "USDT"
            and contract.get("marginAsset") == "USDT"
            and contract.get("underlyingType") == "COIN"
            and re.fullmatch(r"[A-Z0-9]+USDT", symbol)
            and symbol.removesuffix("USDT") not in stable_bases
        ):
            active.add(symbol)
    if not active:
        raise RuntimeError("Binance 未回傳交易中的 USDT 加密永續合約")

    ticker_rows = _http_json_url(f"{BINANCE_FUTURES_DATA_URL}/ticker/24hr")
    selected: list[tuple[float, str]] = []
    for row in ticker_rows if isinstance(ticker_rows, list) else []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper()
        if symbol not in active:
            continue
        try:
            volume = float(row.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        if volume > 0:
            selected.append((volume, symbol))
    selected.sort(key=lambda item: (-item[0], item[1]))
    return [
        Instrument(
            ticker=symbol,
            symbol=symbol,
            exchange="BINANCE",
            market="幣安 USDT 永續",
            session=CRYPTO_SESSION,
            name=f"{symbol.removesuffix('USDT')} / USDT 永續",
            industry="USDT 永續合約",
        )
        for _, symbol in selected[:configured]
    ]


def fetch_binance_crypto_perpetual_symbols() -> list[str]:
    """Return every live USDⓈ-M crypto perpetual in TradingView import format.

    Binance's exchange-info payload classifies the underlying as ``COIN``. The
    separate TradFi equity perpetuals do not reliably appear in every regional
    public API response, so those use the curated stock-perp universe below.
    """
    payload = _http_json_url(BINANCE_FUTURES_INFO_URL)
    rows = payload.get("symbols", []) if isinstance(payload, dict) else []
    symbols: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper()
        if (
            row.get("status") == "TRADING"
            and row.get("contractType") == "PERPETUAL"
            and row.get("quoteAsset") == "USDT"
            and row.get("marginAsset") == "USDT"
            and row.get("underlyingType") == "COIN"
            and re.fullmatch(r"[A-Z0-9]+USDT", symbol)
        ):
            symbols.add(f"BINANCE:{symbol}.P")
    if not symbols:
        raise RuntimeError("Binance 未回傳交易中的 USDT 加密永續合約")
    return sorted(symbols)


def binance_stock_perpetual_symbols() -> list[str]:
    """Return the Binance TradFi individual-stock perpetual universe."""
    return [f"BINANCE:{symbol}USDT.P" for symbol in BINANCE_STOCK_PERPETUALS]


def _download_binance_frame(symbol: str, timeframe: Timeframe) -> pd.DataFrame:
    rows = _http_json_url(
        f"{BINANCE_FUTURES_DATA_URL}/klines?symbol={symbol}&interval={timeframe.key}&limit=120"
    )
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
            "open": open_price,
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
    """Find a long-only reclaim after a death cross below the ribbon.

    White is AI Momentum's ``kernClose`` and yellow is its ``zoneMid``.  The
    death-cross candle *body* (both open and close), white line, and yellow
    line must all be below the lower EMA 50/100 ribbon edge.  They must remain
    below that edge throughout the setup; a candle body re-entering the ribbon
    invalidates the pending setup.  A long reclaim needs a completed close to
    cross above white while white remains below yellow.  This function never
    emits a short signal.
    """
    if features is None or len(features) < 2:
        return []

    active_death_cross: int | None = None
    events: list[dict[str, int]] = []
    for position in range(1, len(features)):
        row = features.iloc[position]
        previous = features.iloc[position - 1]
        values = (
            row["open"],
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
        open_price = float(row["open"])
        lower_edge = float(row["trend_lower_edge"])
        # A close-only comparison produced false positives when a candle
        # opened inside/above the ribbon and merely closed below it.  The user
        # requires an actual body below the ribbon before the death cross can
        # arm a later long reclaim.
        fully_below_ribbon = max(open_price, close, white, yellow) < lower_edge
        is_death_cross = prior_white >= prior_yellow and white < yellow
        if is_death_cross and fully_below_ribbon:
            active_death_cross = position

        if active_death_cross is None:
            continue
        if not fully_below_ribbon:
            active_death_cross = None
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


def td_trend_position(features: pd.DataFrame | None, position: int) -> str:
    """Classify the TD bar's close relative to the EMA 50/100 ribbon."""
    if features is None or position >= len(features):
        return "unavailable"
    row = features.iloc[position]
    close = float(row["close"])
    lower = float(row["trend_lower_edge"])
    upper = float(row["trend_upper_edge"])
    if not all(np.isfinite(value) for value in (close, lower, upper)):
        return "unavailable"
    if close > upper:
        return "above_ribbon"
    if close < lower:
        return "below_ribbon"
    return "inside_ribbon"


def weekly_open_vs_white(
    frame: pd.DataFrame,
    features: pd.DataFrame | None,
    position: int,
    session: MarketSession,
) -> dict[str, object]:
    """Compare the signal week's first completed open with its white line.

    The comparison is made at the first available bar of the signal's local
    calendar week.  Holidays therefore use the first actual session, not a
    synthetic Monday opening price.
    """
    unavailable: dict[str, object] = {
        "weekly_open_vs_white": "unavailable",
        "week_open_price": None,
        "week_open_white": None,
    }
    if features is None or position >= len(frame) or position >= len(features) or "Open" not in frame.columns:
        return unavailable
    timestamp = pd.Timestamp(frame.index[position])
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(session.timezone)
    local_timestamp = timestamp.tz_convert(session.timezone)
    week_start = local_timestamp.date() - timedelta(days=local_timestamp.weekday())
    week_position = position
    for candidate in range(position, -1, -1):
        candidate_time = pd.Timestamp(frame.index[candidate])
        if candidate_time.tzinfo is None:
            candidate_time = candidate_time.tz_localize(session.timezone)
        if candidate_time.tz_convert(session.timezone).date() < week_start:
            break
        week_position = candidate
    week_open = float(pd.to_numeric(frame["Open"].iloc[week_position], errors="coerce"))
    white = float(features["white_kernel"].iloc[week_position])
    if not all(np.isfinite(value) for value in (week_open, white)):
        return unavailable
    tolerance = max(abs(white) * 0.0005, 0.01)
    state = "above_white" if week_open > white + tolerance else "below_white" if week_open < white - tolerance else "at_white"
    return {
        "weekly_open_vs_white": state,
        "week_open_price": round(week_open, 8),
        "week_open_white": round(white, 8),
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


def weekly_white_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate the Trend Trader white line on weekly OHLC bars.

    The supplied Trend Trader script uses an EMA 50 as its short/white line.
    ``white_at_open`` replaces the current weekly close with its open so the
    opening comparison is not distorted by the move that occurred afterwards.
    """
    columns = ["open", "high", "low", "close", "white", "white_at_open"]
    if not {"Open", "High", "Low", "Close"}.issubset(frame.columns):
        return pd.DataFrame(index=frame.index, columns=columns)
    open_price = pd.to_numeric(frame["Open"], errors="coerce")
    high = pd.to_numeric(frame["High"], errors="coerce")
    low = pd.to_numeric(frame["Low"], errors="coerce")
    close = pd.to_numeric(frame["Close"], errors="coerce")
    white = close.ewm(
        span=WEEKLY_WHITE_LENGTH,
        adjust=False,
        min_periods=WEEKLY_WHITE_LENGTH,
    ).mean()
    close_at_open = close.copy()
    if not close_at_open.empty:
        close_at_open.iloc[-1] = open_price.iloc[-1]
    white_at_open = close_at_open.ewm(
        span=WEEKLY_WHITE_LENGTH,
        adjust=False,
        min_periods=WEEKLY_WHITE_LENGTH,
    ).mean()
    return pd.DataFrame(
        {
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "white": white,
            "white_at_open": white_at_open,
        },
        index=frame.index,
    )


def weekly_reclaim_event(features: pd.DataFrame) -> dict[str, object] | None:
    """Return the active long-only weekly white-line recovery.

    A valid setup needs a *weekly body* below the EMA 50 white line, followed
    by a close back above it within the next three weeks.  The priority setup
    is the *first* recovery week: it opens above white, dips below it during
    the week, then closes back above it.  The second and third weeks may stay
    visible as lower-priority follow-through, but they cannot become the
    direct-focus setup themselves.
    """
    if len(features) < WEEKLY_WHITE_LENGTH + 2:
        return None
    latest = len(features) - 1
    last = features.iloc[latest]
    required = (last["open"], last["low"], last["close"], last["white"], last["white_at_open"])
    if not all(np.isfinite(float(value)) for value in required):
        return None
    last_white = float(last["white"])
    white_at_open = float(last["white_at_open"])
    tolerance = max(abs(last_white) * 0.0005, 0.01)
    open_tolerance = max(abs(white_at_open) * 0.0005, 0.01)
    week_open_above = float(last["open"]) > white_at_open + open_tolerance
    week_close_above = float(last["close"]) > last_white + tolerance
    # This is still an active watchlist rather than a historical archive: the
    # latest weekly price needs to hold above white.  Its current opening is
    # not required for a second/third-week follow-through card.
    if not week_close_above:
        return None

    first_reclaim = max(1, latest - WEEKLY_RECLAIM_VISIBLE_WEEKS)
    selected: dict[str, int] | None = None
    for reclaim_position in range(latest, first_reclaim - 1, -1):
        reclaim = features.iloc[reclaim_position]
        prior = features.iloc[reclaim_position - 1]
        reclaim_values = (reclaim["close"], reclaim["white"], prior["close"], prior["white"])
        if not all(np.isfinite(float(value)) for value in reclaim_values):
            continue
        reclaim_white = float(reclaim["white"])
        reclaim_tolerance = max(abs(reclaim_white) * 0.0005, 0.01)
        crossed_back = (
            float(reclaim["close"]) > reclaim_white + reclaim_tolerance
            and float(prior["close"]) <= float(prior["white"]) + reclaim_tolerance
        )
        if not crossed_back:
            continue
        breakdown_start = max(0, reclaim_position - WEEKLY_RECLAIM_LOOKBACK_WEEKS)
        for break_position in range(reclaim_position - 1, breakdown_start - 1, -1):
            broken = features.iloc[break_position]
            broken_values = (broken["open"], broken["close"], broken["white"])
            if not all(np.isfinite(float(value)) for value in broken_values):
                continue
            broken_white = float(broken["white"])
            broken_tolerance = max(abs(broken_white) * 0.0005, 0.01)
            body_below_white = min(float(broken["open"]), float(broken["close"])) < broken_white - broken_tolerance
            if body_below_white:
                selected = {"break_position": break_position, "reclaim_position": reclaim_position}
                break
        if selected:
            break
    if selected is None:
        return None

    reclaim_position = selected["reclaim_position"]
    reclaim = features.iloc[reclaim_position]
    reclaim_values = (
        reclaim["open"], reclaim["low"], reclaim["close"], reclaim["white"], reclaim["white_at_open"],
    )
    if not all(np.isfinite(float(value)) for value in reclaim_values):
        return None
    reclaim_white = float(reclaim["white"])
    reclaim_white_at_open = float(reclaim["white_at_open"])
    reclaim_tolerance = max(abs(reclaim_white) * 0.0005, 0.01)
    reclaim_open_tolerance = max(abs(reclaim_white_at_open) * 0.0005, 0.01)
    first_week_open_above = float(reclaim["open"]) > reclaim_white_at_open + reclaim_open_tolerance
    first_week_dipped_below = float(reclaim["low"]) < reclaim_white - reclaim_tolerance
    first_week_closed_above = float(reclaim["close"]) > reclaim_white + reclaim_tolerance
    first_week_pullback_reclaim = bool(
        first_week_open_above and first_week_dipped_below and first_week_closed_above
    )
    age_weeks = latest - reclaim_position
    first_week_open_distance_pct = (float(reclaim["open"]) / reclaim_white_at_open - 1) * 100
    week_open_distance_pct = (float(last["open"]) / white_at_open - 1) * 100
    week_close_distance_pct = (float(last["close"]) / last_white - 1) * 100
    week_dipped_below = float(last["low"]) < last_white - tolerance
    week_reclaimed = bool(
        age_weeks == 0 and week_open_above and week_dipped_below and week_close_above
    )
    weeks_to_reclaim = selected["reclaim_position"] - selected["break_position"]
    score = 50 + {1: 20, 2: 12, 3: 5}.get(weeks_to_reclaim, 0)
    if age_weeks == 0 and week_open_above:
        score += WEEKLY_OPEN_CLOSE_BONUS
    if age_weeks == 0 and first_week_pullback_reclaim:
        score += 20
    second_week_near_white_open = bool(
        age_weeks == 1
        and first_week_open_above
        and week_open_above
        and week_open_distance_pct <= WEEKLY_SECOND_WEEK_NEAR_WHITE_PCT
    )
    if second_week_near_white_open:
        score += WEEKLY_SECOND_WEEK_NEAR_WHITE_BONUS
    return {
        **selected,
        "weeks_to_reclaim": weeks_to_reclaim,
        "age_weeks": age_weeks,
        "week_open_above_white": week_open_above,
        "week_close_above_white": week_close_above,
        "week_white_structure_active": True,
        "week_dipped_below_white": week_dipped_below,
        "week_reclaimed_white": week_reclaimed,
        "first_week_is_current": age_weeks == 0,
        "first_week_open_above_white": first_week_open_above,
        "first_week_dipped_below_white": first_week_dipped_below,
        "first_week_pullback_reclaim": first_week_pullback_reclaim,
        "first_week_open_distance_pct": round(first_week_open_distance_pct, 4),
        "week_open_distance_pct": round(week_open_distance_pct, 4),
        "week_close_distance_pct": round(week_close_distance_pct, 4),
        "second_week_near_white_open": second_week_near_white_open,
        "second_week_near_white_threshold_pct": WEEKLY_SECOND_WEEK_NEAR_WHITE_PCT,
        "week_open": round(float(last["open"]), 8),
        "week_low": round(float(last["low"]), 8),
        "week_close": round(float(last["close"]), 8),
        "white_line": round(last_white, 8),
        "white_at_open": round(white_at_open, 8),
        "score": score,
    }


def _weekly_hourly_state_unavailable() -> dict[str, object]:
    """Use explicit fields when a current weekly candidate lacks 1h data."""
    return {
        "hourly_status_available": False,
        "hourly_above_white": False,
        "hourly_reclaim_count": 0,
        "hourly_second_reclaim": False,
        "hourly_second_reclaim_bars_ago": None,
        "hourly_second_reclaim_within_four_bars": False,
        "hourly_last_reclaim_time": None,
        "hourly_bar_time": None,
        "hourly_close": None,
        "hourly_white_line": None,
        "hourly_white_distance_pct": None,
    }


def _timestamp_in_session(index_value: object, session: MarketSession) -> pd.Timestamp:
    timestamp = pd.Timestamp(index_value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(session.timezone)
    return timestamp.tz_convert(session.timezone)


def hourly_state_since_weekly_reclaim(
    raw: pd.DataFrame,
    session: MarketSession,
    weekly_reclaim_index: object,
    now: datetime,
) -> dict[str, object]:
    """Return the live hourly white-line state after the weekly reclaim.

    ``刷上去第二次`` is deliberately counted as actual hourly close cross-ups
    from at/below the white line to above it, starting with the week that
    produced the weekly reclaim.  Merely remaining above white does not inflate
    this count.
    """
    unavailable = _weekly_hourly_state_unavailable()
    hourly_timeframe = next(item for item in TIMEFRAMES if item.key == "1h")
    frame = confirmed_bars(raw, hourly_timeframe, session, now)
    if len(frame) < TREND_RIBBON_FAST_LENGTH + 2:
        return unavailable
    features = ai_momentum_features(frame)
    if features.empty or len(features) < 2:
        return unavailable

    anchor = _timestamp_in_session(weekly_reclaim_index, session)
    timestamps = [_timestamp_in_session(value, session) for value in features.index]
    reclaim_positions: list[int] = []
    for position in range(1, len(features)):
        if timestamps[position] < anchor:
            continue
        row = features.iloc[position]
        previous = features.iloc[position - 1]
        values = (row["close"], row["white_kernel"], previous["close"], previous["white_kernel"])
        if not all(np.isfinite(float(value)) for value in values):
            continue
        white = float(row["white_kernel"])
        prior_white = float(previous["white_kernel"])
        tolerance = max(abs(white) * 0.0005, 0.01)
        crossed_up = (
            float(previous["close"]) <= prior_white + tolerance
            and float(row["close"]) > white + tolerance
        )
        if crossed_up:
            reclaim_positions.append(position)

    latest = features.iloc[-1]
    latest_values = (latest["close"], latest["white_kernel"])
    if not all(np.isfinite(float(value)) for value in latest_values):
        return unavailable
    hourly_close = float(latest["close"])
    hourly_white = float(latest["white_kernel"])
    latest_tolerance = max(abs(hourly_white) * 0.0005, 0.01)
    above_white = hourly_close > hourly_white + latest_tolerance
    last_reclaim_position = reclaim_positions[-1] if reclaim_positions else None
    second_reclaim_bars_ago = (
        len(features) - 1 - last_reclaim_position
        if len(reclaim_positions) >= 2 and last_reclaim_position is not None
        else None
    )
    second_reclaim_within_four_bars = bool(
        above_white
        and second_reclaim_bars_ago is not None
        and second_reclaim_bars_ago <= HOURLY_SECOND_RECLAIM_RECENCY_BARS
    )
    return {
        "hourly_status_available": True,
        "hourly_above_white": above_white,
        "hourly_reclaim_count": len(reclaim_positions),
        "hourly_second_reclaim": bool(above_white and len(reclaim_positions) >= 2),
        "hourly_second_reclaim_bars_ago": second_reclaim_bars_ago,
        "hourly_second_reclaim_within_four_bars": second_reclaim_within_four_bars,
        "hourly_last_reclaim_time": (
            format_bar_time(features.index[last_reclaim_position], hourly_timeframe, session)
            if last_reclaim_position is not None
            else None
        ),
        "hourly_bar_time": format_bar_time(features.index[-1], hourly_timeframe, session),
        "hourly_close": round(hourly_close, 8),
        "hourly_white_line": round(hourly_white, 8),
        "hourly_white_distance_pct": round((hourly_close / hourly_white - 1) * 100, 4),
    }


def format_weekly_bar_time(index_value: object, session: MarketSession) -> str:
    timestamp = pd.Timestamp(index_value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(session.timezone)
    return timestamp.tz_convert(session.timezone).strftime("%Y-%m-%d 週線")


def collect_signals(
    us_instruments: list[Instrument],
    taiwan_underlyings: dict[str, str],
    taiwan_industries: dict[str, str],
    binance_instruments: list[Instrument],
    pepperstone_instruments: list[Instrument],
    timeframe: Timeframe,
    now: datetime,
    public_profile_cache: dict[str, str | None] | None = None,
) -> dict[str, object]:
    records = download_yahoo_records(us_instruments, timeframe)
    records.extend(download_yahoo_records(pepperstone_instruments, timeframe))
    records.extend(download_taiwan_records(taiwan_underlyings, taiwan_industries, timeframe))
    records.extend(download_binance_records(binance_instruments, timeframe))
    signals: list[dict[str, object]] = []
    trend_reclaim_signals: list[dict[str, object]] = []
    taiwan_universe: dict[str, dict[str, str]] = {}
    scanned_by_market: dict[str, int] = {}
    latest_completed: list[tuple[pd.Timestamp, MarketSession]] = []

    for instrument, raw in records:
        frame = confirmed_bars(raw, timeframe, instrument.session, now)
        if len(frame) < 13:
            continue
        scanned_by_market[instrument.market] = scanned_by_market.get(instrument.market, 0) + 1
        if instrument.market == "台股":
            category = TAIWAN_PRODUCT_CATEGORIES.get(instrument.symbol)
            if not category:
                category = f"產業：{instrument.industry}" if instrument.industry else "其他台股"
            taiwan_universe[instrument.symbol] = {
                "symbol": instrument.symbol,
                "exchange": instrument.exchange,
                "tradingview_symbol": tradingview_symbol_for(instrument),
                "product_category": category,
                "industry": instrument.industry or "",
            }
        _, events = sequential_history(frame)
        latest_completed.append((pd.Timestamp(frame.index[-1]), instrument.session))
        today_change_pct = latest_day_change_pct(frame, timeframe, instrument.session)
        recent_bars = int(os.getenv("RECENT_SIGNAL_BARS", "8"))
        if recent_bars < 1 or recent_bars > 20:
            raise ValueError("RECENT_SIGNAL_BARS 必須介於 1 到 20")
        # `RECENT_SIGNAL_BARS=8` means a signal remains visible through the
        # eighth completed bar after it occurred (ages 0 through 8).  The
        # inclusive comparison keeps the final configured bar visible.
        recent_events = [
            event for event in events
            if len(frame) - 1 - int(event["position"]) <= recent_bars
        ]
        # Resolve public company descriptions only for names that actually
        # create a card.  That keeps the 200+ Taiwan universe scan fast while
        # making the card classification materially more specific.
        card_product_category = (
            product_category_for(instrument, public_profile_cache)
            if recent_events
            else None
        )
        # All card timeframes need the ribbon position and weekly-open/white
        # comparison.  The stricter bearish-Momentum confirmation remains a
        # 15-minute / one-hour filter only.
        features = ai_momentum_features(frame)
        for event in recent_events:
            position = int(event["position"])
            age_bars = len(frame) - 1 - position
            sparkline, sparkline_signal_index = signal_sparkline(frame, position)
            signals.append(
                {
                    "symbol": instrument.symbol,
                    "name": instrument.name,
                    "industry": instrument.industry,
                    "product_category": card_product_category,
                    "exchange": instrument.exchange,
                    "tradingview_symbol": tradingview_symbol_for(instrument),
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
                    "td_trend_position": td_trend_position(features, position),
                    **weekly_open_vs_white(frame, features, position, instrument.session),
                    "sparkline": sparkline,
                    "sparkline_signal_index": sparkline_signal_index,
                }
            )

        if timeframe.key in MOMENTUM_TIMEFRAME_KEYS:
            recent_reclaims = [
                event
                for event in trend_reclaim_events(features)
                if len(frame) - 1 - int(event["position"]) <= recent_bars
            ]
            for event in recent_reclaims:
                if card_product_category is None:
                    card_product_category = product_category_for(instrument, public_profile_cache)
                position = int(event["position"])
                death_position = int(event["death_cross_position"])
                sparkline, sparkline_signal_index = signal_sparkline(frame, position)
                sparkline_start = max(0, len(frame) - 30)
                trend_reclaim_signals.append(
                    {
                        "symbol": instrument.symbol,
                        "name": instrument.name,
                        "industry": instrument.industry,
                        "product_category": card_product_category,
                        "exchange": instrument.exchange,
                        "tradingview_symbol": tradingview_symbol_for(instrument),
                        "market": instrument.market,
                        "side": "buy",
                        "signal_type": "long_reclaim",
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
        "recent_bars": int(os.getenv("RECENT_SIGNAL_BARS", "8")),
        "last_completed_bar_et": "已依各市場最後完成 K 棒計算" if latest_completed else None,
        "signals": signals,
        "trend_reclaim_signals": trend_reclaim_signals,
        "taiwan_pine_screener_universe": sorted(
            taiwan_universe.values(),
            key=lambda item: (
                str(item["product_category"]),
                str(item["industry"]),
                str(item["tradingview_symbol"]),
            ),
        ),
    }


def collect_weekly_reclaims(
    us_instruments: list[Instrument],
    taiwan_underlyings: dict[str, str],
    taiwan_industries: dict[str, str],
    binance_instruments: list[Instrument],
    pepperstone_instruments: list[Instrument],
    now: datetime,
    public_profile_cache: dict[str, str | None] | None = None,
) -> dict[str, object]:
    """Scan the active week for white-line breakdown/reclaim structures."""
    timeframe = WEEKLY_RECLAIM_TIMEFRAME
    records = download_yahoo_records(us_instruments, timeframe)
    records.extend(download_yahoo_records(pepperstone_instruments, timeframe))
    records.extend(download_taiwan_records(taiwan_underlyings, taiwan_industries, timeframe))
    records.extend(download_binance_records(binance_instruments, timeframe))
    signals: list[dict[str, object]] = []
    weekly_candidates: list[tuple[dict[str, object], Instrument, object]] = []
    scanned_by_market: dict[str, int] = {}

    for instrument, raw in records:
        frame = raw.dropna(subset=["Open", "High", "Low", "Close"]).copy().sort_index()
        if len(frame) < WEEKLY_WHITE_LENGTH + 2:
            continue
        scanned_by_market[instrument.market] = scanned_by_market.get(instrument.market, 0) + 1
        event = weekly_reclaim_event(weekly_white_features(frame))
        if event is None:
            continue
        product_category = product_category_for(instrument, public_profile_cache)
        reclaim_position = int(event["reclaim_position"])
        break_position = int(event["break_position"])
        sparkline, sparkline_signal_index = signal_sparkline(frame, reclaim_position, maximum_bars=26)
        sparkline_start = max(0, len(frame) - 26)
        signal = {
                "symbol": instrument.symbol,
                "name": instrument.name,
                "industry": instrument.industry,
                "product_category": product_category,
                "exchange": instrument.exchange,
                "tradingview_symbol": tradingview_symbol_for(instrument),
                "market": instrument.market,
                "signal_type": "weekly_white_reclaim",
                "side": "buy",
                "bar_time_et": format_weekly_bar_time(frame.index[-1], instrument.session),
                "occurred_at_utc": occurrence_time_utc(frame.index[reclaim_position], instrument.session),
                "last_price": round(float(frame["Close"].iloc[-1]), 8),
                "week_change_pct": latest_day_change_pct(frame, timeframe, instrument.session),
                "break_time": format_weekly_bar_time(frame.index[break_position], instrument.session),
                "reclaim_time": format_weekly_bar_time(frame.index[reclaim_position], instrument.session),
                "sparkline": sparkline,
                "sparkline_signal_index": sparkline_signal_index,
                "sparkline_break_index": (
                    break_position - sparkline_start if break_position >= sparkline_start else None
                ),
                **event,
            }
        signals.append(signal)
        # Keep the raw weekly bar index only in memory.  It anchors the
        # hourly "first/second stand back above white" count to this weekly
        # recovery rather than to an arbitrary trailing number of hours.
        weekly_candidates.append((signal, instrument, frame.index[reclaim_position]))

    hourly_timeframe = next(item for item in TIMEFRAMES if item.key == "1h")
    yahoo_hourly_candidates = [
        instrument
        for _, instrument, _ in weekly_candidates
        if instrument.market != "幣安 USDT 永續"
    ]
    binance_hourly_candidates = [
        instrument
        for _, instrument, _ in weekly_candidates
        if instrument.market == "幣安 USDT 永續"
    ]
    hourly_records = download_yahoo_records(yahoo_hourly_candidates, hourly_timeframe)
    hourly_records.extend(download_binance_records(binance_hourly_candidates, hourly_timeframe))
    hourly_by_ticker = {instrument.ticker: raw for instrument, raw in hourly_records}
    for signal, instrument, weekly_reclaim_index in weekly_candidates:
        hourly_raw = hourly_by_ticker.get(instrument.ticker)
        hourly_state = (
            hourly_state_since_weekly_reclaim(
                hourly_raw, instrument.session, weekly_reclaim_index, now
            )
            if hourly_raw is not None
            else _weekly_hourly_state_unavailable()
        )
        signal.update(hourly_state)
        if bool(hourly_state["hourly_above_white"]):
            signal["score"] = int(signal["score"]) + HOURLY_WHITE_ABOVE_BONUS
        if bool(
            signal["first_week_is_current"]
            and signal["first_week_pullback_reclaim"]
            and hourly_state["hourly_second_reclaim_within_four_bars"]
        ):
            signal["score"] = int(signal["score"]) + HOURLY_SECOND_RECLAIM_BONUS
        signal["direct_focus"] = bool(
            signal["week_white_structure_active"]
            and signal["first_week_is_current"]
            and signal["first_week_pullback_reclaim"]
            and hourly_state["hourly_above_white"]
            and hourly_state["hourly_second_reclaim_within_four_bars"]
        )

    signals.sort(
        key=lambda item: (
            not bool(item.get("direct_focus")),
            -int(item["score"]),
            str(item["market"]),
            str(item["tradingview_symbol"]),
        )
    )
    return {
        "key": timeframe.key,
        "label": timeframe.label,
        "tradingview_interval": timeframe.tradingview_interval,
        "white_line_definition": f"Trend Trader EMA {WEEKLY_WHITE_LENGTH}",
        "lookback_weeks": WEEKLY_RECLAIM_LOOKBACK_WEEKS,
        "visible_weeks": WEEKLY_RECLAIM_VISIBLE_WEEKS,
        "scanned_symbols": sum(scanned_by_market.values()),
        "scanned_by_market": scanned_by_market,
        "signals": signals,
    }


def tradingview_export_symbols(frame_list: Iterable[dict[str, object]]) -> list[str]:
    """Return an import-safe, long-only watchlist in product-led order."""
    # TradingView watchlist imports accept ticker lines only.  Product and
    # industry therefore define the deterministic line order rather than being
    # inserted as headings that would make the TXT fail to import.
    market_order = {"台股": 0, "美股": 1, "幣安 USDT 永續": 2, "Pepperstone CFD": 3}
    tradingview_entries: dict[str, dict] = {}
    for timeframe in frame_list:
        signals = timeframe.get("signals", []) if isinstance(timeframe, dict) else []
        for signal in signals if isinstance(signals, list) else []:
            if not isinstance(signal, dict) or signal.get("side") != "buy":
                continue
            symbol = str(signal.get("tradingview_symbol") or "").strip()
            if not symbol:
                exchange = str(signal.get("exchange") or "").strip().upper()
                ticker = str(signal.get("symbol") or "").strip().upper()
                symbol = f"{exchange}:{ticker}" if exchange and ticker else ""
            if not symbol:
                continue
            previous = tradingview_entries.get(symbol)
            if previous is None or str(signal.get("occurred_at_utc") or "") > str(previous.get("occurred_at_utc") or ""):
                tradingview_entries[symbol] = signal

    def tradingview_sort_key(item: tuple[str, dict]) -> tuple[int, str, str, str]:
        symbol, signal = item
        market = str(signal.get("market") or "")
        product = str(signal.get("product_category") or signal.get("industry") or "其他")
        industry = str(signal.get("industry") or "")
        return (market_order.get(market, 99), product.casefold(), industry.casefold(), symbol)

    return [symbol for symbol, _ in sorted(tradingview_entries.items(), key=tradingview_sort_key)]


def weekly_reclaim_export_symbols(weekly_frame: dict[str, object]) -> list[str]:
    """Return the active weekly white-reclaim monitor as a TradingView list."""
    market_order = {"台股": 0, "美股": 1, "幣安 USDT 永續": 2, "Pepperstone CFD": 3}
    entries: dict[str, dict[str, object]] = {}
    signals = weekly_frame.get("signals", []) if isinstance(weekly_frame, dict) else []
    for signal in signals if isinstance(signals, list) else []:
        if not isinstance(signal, dict):
            continue
        symbol = str(signal.get("tradingview_symbol") or "").strip()
        if not symbol:
            continue
        prior = entries.get(symbol)
        if prior is None or int(signal.get("score") or 0) > int(prior.get("score") or 0):
            entries[symbol] = signal
    return [
        symbol
        for symbol, _ in sorted(
            entries.items(),
            key=lambda item: (
                -int(item[1].get("score") or 0),
                market_order.get(str(item[1].get("market") or ""), 99),
                str(item[1].get("product_category") or item[1].get("industry") or "").casefold(),
                item[0],
            ),
        )
    ]


def write_payload(
    frames: Iterable[dict[str, object]],
    weekly_reclaim: dict[str, object],
    now: datetime,
    errors: list[str],
    binance_crypto_perpetuals: list[str] | None = None,
) -> None:
    source = (
        "美股、台股與 Pepperstone CFD K 線：Yahoo Finance via yfinance；"
        "台股監測清單：公開市場資料整理；幣安：24 小時成交額最高的 USDT 永續合約"
        "（預設前 200 檔）與 USDⓈ-M 公開 K 線；Binance 加密 USDT 永續合約清單：Futures exchangeInfo 公開資料；"
        "Pepperstone CFD 池：黃金、白銀、原油、主要股價指數與核心貨幣對；"
        "技術計算採 Yahoo Finance 對應期貨／指數代理 K 線，非 Pepperstone CFD 成交量。"
    )
    if errors:
        source += " 本次部分來源未更新：" + "；".join(errors)
    frame_list = list(frames)
    payload = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "market_status": "open" if is_regular_session(now) else "closed",
        "source": source,
        "timeframes": frame_list,
        "weekly_reclaim": weekly_reclaim,
    }
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # The static file is a ready-to-upload TradingView watchlist for the
    # default buy-side view.  The browser can additionally export any active
    # filter combination without waiting for another Actions run.
    tradingview_symbols = tradingview_export_symbols(frame_list)
    TRADINGVIEW_EXPORT_FILE.write_text(
        "\n".join(tradingview_symbols) + ("\n" if tradingview_symbols else ""),
        encoding="utf-8",
    )
    weekly_symbols = weekly_reclaim_export_symbols(weekly_reclaim)
    WEEKLY_RECLAIM_EXPORT_FILE.write_text(
        "\n".join(weekly_symbols) + ("\n" if weekly_symbols else ""),
        encoding="utf-8",
    )
    # A stable Taiwan universe for Pine Screener. Unlike the TD export above,
    # this contains every Taiwan symbol successfully scanned in the current
    # run, so TradingView can discover future signals rather than only opening
    # symbols already in the 8-bar TD window.
    taiwan_universe: dict[str, dict[str, object]] = {}
    for timeframe in frame_list:
        entries = timeframe.get("taiwan_pine_screener_universe", []) if isinstance(timeframe, dict) else []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("tradingview_symbol") or "").strip()
            if symbol:
                taiwan_universe[symbol] = entry
    ordered_taiwan_symbols = [
        symbol
        for symbol, _ in sorted(
            taiwan_universe.items(),
            key=lambda item: (
                str(item[1].get("product_category") or "其他台股").casefold(),
                str(item[1].get("industry") or "").casefold(),
                item[0],
            ),
        )
    ]
    TAIWAN_PINE_SCREENER_FILE.write_text(
        "\n".join(ordered_taiwan_symbols) + ("\n" if ordered_taiwan_symbols else ""),
        encoding="utf-8",
    )
    # A stable, non-signal-only Pepperstone universe for direct TradingView
    # import.  This mirrors the monitoring pool so it remains useful even
    # when none of the 18 products currently has a qualifying TD event.
    pepperstone_symbols = [
        tradingview_symbol_for(instrument)
        for instrument in fetch_pepperstone_instruments()
    ]
    PEPPERSTONE_CFD_FILE.write_text(
        "\n".join(pepperstone_symbols) + "\n",
        encoding="utf-8",
    )
    # Full live Binance crypto-perpetual universe. These are not signal-only
    # exports; import the list into TradingView to scan every active contract.
    if binance_crypto_perpetuals is not None:
        BINANCE_CRYPTO_PERPETUALS_FILE.write_text(
            "\n".join(binance_crypto_perpetuals) + ("\n" if binance_crypto_perpetuals else ""),
            encoding="utf-8",
        )
    # Individual-equity TradFi perpetuals only. ETFs, indexes and commodities
    # are intentionally excluded so this remains the requested stock list.
    stock_perps = binance_stock_perpetual_symbols()
    BINANCE_STOCK_PERPETUALS_FILE.write_text(
        "\n".join(stock_perps) + "\n",
        encoding="utf-8",
    )


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
    try:
        binance_crypto_perpetuals = fetch_binance_crypto_perpetual_symbols()
    except Exception as exc:
        logging.warning("幣安加密永續合約清單讀取失敗：%s", exc)
        binance_crypto_perpetuals = None
        errors.append("幣安加密永續合約清單讀取失敗")
    pepperstone_instruments = fetch_pepperstone_instruments()
    public_profile_cache: dict[str, str | None] = {}

    frames = [
        collect_signals(
            us_instruments,
            taiwan_underlyings,
            taiwan_industries,
            binance_instruments,
            pepperstone_instruments,
            timeframe,
            now,
            public_profile_cache,
        )
        for timeframe in TIMEFRAMES
    ]
    weekly_reclaim = collect_weekly_reclaims(
        us_instruments,
        taiwan_underlyings,
        taiwan_industries,
        binance_instruments,
        pepperstone_instruments,
        now,
        public_profile_cache,
    )
    write_payload(frames, weekly_reclaim, now, errors, binance_crypto_perpetuals)
    logging.info(
        "Sequential 已更新：%s",
        ", ".join(f"{item['label']} {len(item['signals'])} 個訊號" for item in frames)
        + f"；週線白線收復 {len(weekly_reclaim['signals'])} 個",
    )


if __name__ == "__main__":
    main()
