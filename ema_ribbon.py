#!/usr/bin/env python3
"""Pure daily EMA ribbon compression and bullish-expansion detector."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


EMA_LENGTHS = (9, 21, 50, 150, 200)


@dataclass(frozen=True)
class EmaRibbonSettings:
    compression_threshold_pct: float = 3.0
    compression_lookback_bars: int = 60
    alignment_bars: int = 3
    expansion_compare_bars: int = 5
    minimum_expanding_gaps: int = 3
    minimum_bars: int = 220

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _numeric_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"Open", "High", "Low", "Close"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    clean = frame.loc[:, ["Open", "High", "Low", "Close"]].copy()
    for column in clean.columns:
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    return clean.dropna()


def ema_ribbon_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return OHLC plus EMA, spread, alignment, and normalized gap columns."""
    clean = _numeric_ohlc(frame)
    if clean.empty:
        return clean
    close = clean["Close"]
    for length in EMA_LENGTHS:
        clean[f"ema{length}"] = close.ewm(span=length, adjust=False).mean()
    ema_columns = [f"ema{length}" for length in EMA_LENGTHS]
    clean["ema_spread_pct"] = (
        (clean[ema_columns].max(axis=1) - clean[ema_columns].min(axis=1))
        / close.where(close > 0)
        * 100.0
    )
    clean["bullish_aligned"] = True
    for fast, slow in zip(EMA_LENGTHS, EMA_LENGTHS[1:]):
        clean["bullish_aligned"] &= clean[f"ema{fast}"] > clean[f"ema{slow}"]
        clean[f"gap_{fast}_{slow}_pct"] = (
            (clean[f"ema{fast}"] - clean[f"ema{slow}"]) / close.where(close > 0) * 100.0
        )
    return clean


def ema_ribbon_signal(
    frame: pd.DataFrame,
    settings: EmaRibbonSettings = EmaRibbonSettings(),
) -> dict[str, object] | None:
    """Classify the newest daily bar without using its close for the open test."""
    features = ema_ribbon_features(frame)
    required = max(
        settings.minimum_bars,
        settings.compression_lookback_bars + 2,
        settings.alignment_bars,
        settings.expansion_compare_bars + 1,
    )
    if len(features) < required:
        return None

    latest = features.iloc[-1]
    previous = features.iloc[-2]
    compare = features.iloc[-1 - settings.expansion_compare_bars]
    prior_window = features["ema_spread_pct"].iloc[
        -1 - settings.compression_lookback_bars : -1
    ]
    compression_pct = float(prior_window.min())
    if compression_pct > settings.compression_threshold_pct:
        return None

    aligned_window = features["bullish_aligned"].iloc[-settings.alignment_bars :]
    if not bool(aligned_window.all()):
        return None

    gap_columns = [
        f"gap_{fast}_{slow}_pct"
        for fast, slow in zip(EMA_LENGTHS, EMA_LENGTHS[1:])
    ]
    gap_expansion = {
        column.removeprefix("gap_"): float(latest[column]) > float(compare[column])
        for column in gap_columns
    }
    expanding_gap_count = sum(gap_expansion.values())
    spread_expanding = float(latest["ema_spread_pct"]) > float(compare["ema_spread_pct"])
    ema9_rising = float(latest["ema9"]) > float(compare["ema9"])
    if (
        expanding_gap_count < settings.minimum_expanding_gaps
        or not spread_expanding
        or not ema9_rising
    ):
        return None

    previous_open = float(previous["Open"])
    previous_close = float(previous["Close"])
    previous_bearish = previous_close < previous_open
    fast_break_lines = [
        length
        for length in (9, 21)
        if previous_bearish
        and previous_open >= float(previous[f"ema{length}"])
        and previous_close < float(previous[f"ema{length}"])
    ]
    current_open = float(latest["Open"])
    previous_ema9 = float(previous["ema9"])
    open_above_previous_ema9 = current_open > previous_ema9
    stage = (
        "open_reclaim"
        if fast_break_lines and open_above_previous_ema9
        else "expansion_watch"
    )

    gap_growth_pct = 0.0
    for column in gap_columns:
        before = abs(float(compare[column]))
        after = float(latest[column])
        gap_growth_pct += (after - before) / max(before, 0.01) * 100.0
    expansion_score = max(0.0, min(100.0, gap_growth_pct / len(gap_columns)))

    return {
        "stage": stage,
        "ema_lengths": list(EMA_LENGTHS),
        "compression_pct": round(compression_pct, 4),
        "current_spread_pct": round(float(latest["ema_spread_pct"]), 4),
        "spread_compare_bars": settings.expansion_compare_bars,
        "expanding_gap_count": expanding_gap_count,
        "gap_expansion": gap_expansion,
        "alignment_bars": settings.alignment_bars,
        "fast_break_lines": fast_break_lines,
        "open_above_previous_ema9": open_above_previous_ema9,
        "current_open": round(current_open, 8),
        "previous_ema9": round(previous_ema9, 8),
        "last_price": round(float(latest["Close"]), 8),
        "expansion_score": round(expansion_score, 2),
        "ema_values": {
            str(length): round(float(latest[f"ema{length}"]), 8)
            for length in EMA_LENGTHS
        },
    }

