#!/usr/bin/env python3
"""Pure EMA compression, below-all-five break, and first-reclaim detector."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


EMA_LENGTHS = (9, 21, 50, 150, 200)


@dataclass(frozen=True)
class EmaRibbonSettings:
    compression_threshold_pct: float = 3.0
    reclaim_window_bars: int = 20
    minimum_bars: int = 220

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _numeric_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"Open", "High", "Low", "Close"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    columns = ["Open", "High", "Low", "Close"]
    if "Volume" in frame.columns:
        columns.append("Volume")
    clean = frame.loc[:, columns].copy()
    for column in clean.columns:
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    return clean.dropna(subset=["Open", "High", "Low", "Close"])


def ema_ribbon_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return OHLC plus EMA, spread, and above/below-all-five columns."""
    clean = _numeric_ohlc(frame)
    if clean.empty:
        return clean
    close = clean["Close"]
    for length in EMA_LENGTHS:
        clean[f"ema{length}"] = close.ewm(span=length, adjust=False).mean()
    ema_columns = [f"ema{length}" for length in EMA_LENGTHS]
    clean["ema_high"] = clean[ema_columns].max(axis=1)
    clean["ema_low"] = clean[ema_columns].min(axis=1)
    clean["ema_spread_pct"] = (
        (clean["ema_high"] - clean["ema_low"])
        / close.where(close > 0)
        * 100.0
    )
    clean["close_above_all"] = close > clean["ema_high"]
    clean["close_below_all"] = close < clean["ema_low"]
    return clean


def ema_ribbon_signal(
    frame: pd.DataFrame,
    settings: EmaRibbonSettings = EmaRibbonSettings(),
) -> dict[str, object] | None:
    """Return the newest completed bar only when it is the first five-line reclaim."""
    features = ema_ribbon_features(frame)
    if len(features) < max(settings.minimum_bars, settings.reclaim_window_bars + 2):
        return None

    latest_position = len(features) - 1
    latest = features.iloc[latest_position]
    if not bool(latest["close_above_all"]):
        return None

    window_start = max(0, latest_position - settings.reclaim_window_bars)
    chosen_compression_position: int | None = None
    chosen_break_position: int | None = None

    for break_position in range(latest_position - 1, window_start, -1):
        if not bool(features.iloc[break_position]["close_below_all"]):
            continue
        prior_compressions = [
            position
            for position in range(window_start, break_position)
            if float(features.iloc[position]["ema_spread_pct"])
            <= settings.compression_threshold_pct
        ]
        if not prior_compressions:
            continue
        if any(
            bool(features.iloc[position]["close_above_all"])
            for position in range(break_position + 1, latest_position)
        ):
            continue
        chosen_compression_position = prior_compressions[-1]
        chosen_break_position = break_position
        break

    if chosen_compression_position is None or chosen_break_position is None:
        return None

    compression_row = features.iloc[chosen_compression_position]
    break_row = features.iloc[chosen_break_position]
    latest_close = float(latest["Close"])
    latest_ema_high = float(latest["ema_high"])
    reclaim_margin_pct = (latest_close / latest_ema_high - 1.0) * 100.0

    return {
        "stage": "five_line_reclaim",
        "ema_lengths": list(EMA_LENGTHS),
        "compression_pct": round(float(compression_row["ema_spread_pct"]), 4),
        "compression_bars_ago": latest_position - chosen_compression_position,
        "break_bars_ago": latest_position - chosen_break_position,
        "break_close": round(float(break_row["Close"]), 8),
        "break_ema_low": round(float(break_row["ema_low"]), 8),
        "current_spread_pct": round(float(latest["ema_spread_pct"]), 4),
        "reclaim_margin_pct": round(reclaim_margin_pct, 4),
        "reclaim_close": round(latest_close, 8),
        "reclaim_ema_high": round(latest_ema_high, 8),
        "last_price": round(latest_close, 8),
        "ema_values": {
            str(length): round(float(latest[f"ema{length}"]), 8)
            for length in EMA_LENGTHS
        },
    }
