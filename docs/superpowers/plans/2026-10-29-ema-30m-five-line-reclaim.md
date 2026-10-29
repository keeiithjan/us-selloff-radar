# 30-Minute EMA Five-Line Reclaim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the daily EMA expansion detector with a confirmed 30-minute compression, below-all-five break, and first above-all-five reclaim monitor.

**Architecture:** Keep the pure EMA calculation in `ema_ribbon.py`, resample already-downloaded 15-minute records into confirmed 30-minute bars inside `sequential.py`, and continue publishing through the existing payload and TXT paths. Update the EMA panel to consume the 15-minute frame's embedded 30-minute monitor and clearly label confirmed-close semantics.

**Tech Stack:** Python 3.12, pandas, unittest, vanilla JavaScript, GitHub Actions

**Spec:** `docs/specs/ema-ribbon-expansion.md`

## Global Constraints

- Only completed 30-minute bars may trigger a signal.
- Compression, break, and first reclaim must occur in order within 20 bars.
- Compression threshold is exactly 3.0% across EMA 9／21／50／150／200.
- Reclaim means close above the highest of all five EMAs, not open above EMA9.
- Reuse 15-minute market downloads; do not add a fourth full-market Yahoo download pass.

---

### Task 1: Pure 30-Minute Reclaim Detector

**Files:**
- Modify: `ema_ribbon.py`
- Modify: `tests/test_ema_ribbon.py`

**Interfaces:**
- Consumes: completed OHLC bars through `ema_ribbon_signal(frame, settings)`.
- Produces: `five_line_reclaim` dictionaries with `compression_bars_ago`, `break_bars_ago`, `reclaim_margin_pct`, `current_spread_pct`, and EMA values.

- [ ] **Step 1: Write boundary tests for ordered compression, break, and first reclaim**

```python
signal = ema_ribbon_signal(five_line_reclaim_frame())
self.assertEqual(signal["stage"], "five_line_reclaim")
self.assertLessEqual(signal["compression_bars_ago"], 20)
self.assertGreater(signal["reclaim_margin_pct"], 0)
```

- [ ] **Step 2: Run tests and confirm the daily open-reclaim implementation fails**

Run: `python -m unittest tests.test_ema_ribbon -v`
Expected: FAIL because the old detector requires bullish alignment and prior-open reclaim.

- [ ] **Step 3: Implement the ordered 20-bar state sequence**

```python
latest_above_all = latest_close > max(latest[f"ema{length}"] for length in EMA_LENGTHS)
break_below_all = close < min(row[f"ema{length}"] for length in EMA_LENGTHS)
compressed = spread_pct <= settings.compression_threshold_pct
```

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_ema_ribbon -v`
Expected: PASS.

### Task 2: 15-Minute Download Reuse and 30-Minute Publishing

**Files:**
- Modify: `sequential.py`
- Modify: `tests/test_ema_ribbon.py`

**Interfaces:**
- Consumes: 15-minute raw records already loaded by `collect_signals()`.
- Produces: `resample_to_30_minutes(frame)` and a 30-minute monitor embedded in the `15m` frame under `ema_ribbon_expansion`.

- [ ] **Step 1: Add resampling and export integration tests**

```python
bars = resample_to_30_minutes(fifteen_minute_frame)
self.assertEqual(len(bars), len(fifteen_minute_frame) // 2)
self.assertEqual(ema_ribbon_export_symbols(frames), ["TWSE:2330"])
```

- [ ] **Step 2: Resample 15-minute records and filter incomplete 30-minute bars**

```python
resampled = resample_to_30_minutes(raw)
ema_frame = confirmed_bars(resampled, EMA_RIBBON_TIMEFRAME, instrument.session, now)
```

- [ ] **Step 3: Increase only Binance 15-minute history to 500 rows**

```python
limit = 500 if timeframe.key == "15m" else 120
```

- [ ] **Step 4: Run focused integration tests**

Run: `python -m unittest tests.test_ema_ribbon -v`
Expected: PASS.

### Task 3: UI Copy, Metrics, and Deployment

**Files:**
- Modify: `index.html`
- Modify: `assets/app.js`
- Modify: `README.md`
- Modify: `sw.js`
- Modify: `tests/test_ema_ribbon_ui.py`

**Interfaces:**
- Consumes: `five_line_reclaim` signal fields from the 15-minute payload frame.
- Produces: a 30-minute panel, TradingView interval `30`, and PWA bundle `20261029-ema-30m1` with cache `kj-radar-shell-v33`.

- [ ] **Step 1: Change UI tests to require 30-minute confirmed-close copy**

```python
self.assertIn("30 分鐘", index_html)
self.assertIn('signal.stage === "five_line_reclaim"', app_js)
self.assertIn('makeTradingViewLink(signal, "30")', app_js)
```

- [ ] **Step 2: Render compression age, break age, and reclaim margin**

```javascript
["距壓縮", `${Number(signal.compression_bars_ago)} 根`]
["距跌破", `${Number(signal.break_bars_ago)} 根`]
["站回幅度", `${Number(signal.reclaim_margin_pct).toFixed(2)}%`]
```

- [ ] **Step 3: Rev PWA assets and documentation**

```javascript
const CACHE_NAME = "kj-radar-shell-v33";
```

- [ ] **Step 4: Run full verification**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS.

Run: `node --check assets/app.js`
Expected: exit 0.

Run: `node --test tests/test_line_reclaim_export.mjs`
Expected: PASS.

- [ ] **Step 5: Commit, push, and verify the deployed payload**

```bash
git add README.md assets/app.js assets/styles.css docs index.html ema_ribbon.py sequential.py sw.js tests
git commit -m "feat: monitor 30-minute five-line EMA reclaims"
git push origin main
```
