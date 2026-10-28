# EMA Ribbon Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily EMA 9／21／50／150／200 compression-to-bullish-expansion monitor with next-session EMA9 opening-reclaim prioritization.

**Architecture:** Keep the indicator math in a focused pure-Python module, call it from the existing daily multi-market scan so quotes are not downloaded twice, and publish the results in the existing JSON plus a TradingView TXT export. Add a self-contained web panel that reads the daily payload and is deployed by the existing scheduled GitHub Pages workflow.

**Tech Stack:** Python 3.12, pandas, standard-library unittest, vanilla JavaScript, HTML/CSS, GitHub Actions, GitHub Pages

**Spec:** `docs/specs/ema-ribbon-expansion.md`

## Global Constraints

- EMA lengths are exactly 9, 21, 50, 150, and 200 daily bars.
- Opening reclaim compares the current open with the previous completed bar's EMA9 to avoid look-ahead and intraday repainting.
- Default compression threshold is 3.0% within 60 prior bars.
- Bullish alignment must persist for 3 bars and expansion is compared with 5 bars earlier.
- Existing TD, white/orange reclaim, big-black, weekly, and export behavior must remain compatible.

---

### Task 1: Pure EMA ribbon detector

**Files:**
- Create: `ema_ribbon.py`
- Test: `tests/test_ema_ribbon.py`

**Interfaces:**
- Consumes: daily OHLC `pandas.DataFrame` with `Open`, `High`, `Low`, and `Close` columns.
- Produces: `ema_ribbon_signal(frame: pd.DataFrame, settings: EmaRibbonSettings = EmaRibbonSettings()) -> dict[str, object] | None`.

- [ ] **Step 1: Write failing tests for compression, expansion, opening reclaim, and look-ahead avoidance**

```python
signal = ema_ribbon_signal(frame)
assert signal is not None
assert signal["stage"] == "open_reclaim"
assert signal["open_above_previous_ema9"] is True
assert signal["fast_break_lines"] == [9]
```

- [ ] **Step 2: Run the focused test and confirm the missing module fails**

Run: `python -m unittest tests.test_ema_ribbon -v`
Expected: FAIL because `ema_ribbon` does not exist.

- [ ] **Step 3: Implement EMA features and deterministic stage classification**

```python
ema = {length: close.ewm(span=length, adjust=False).mean() for length in (9, 21, 50, 150, 200)}
spread_pct = (max_ema - min_ema) / close * 100.0
open_above_previous_ema9 = float(open_.iloc[-1]) > float(ema[9].iloc[-2])
```

- [ ] **Step 4: Run the detector tests**

Run: `python -m unittest tests.test_ema_ribbon -v`
Expected: PASS.

- [ ] **Step 5: Commit detector and tests**

```bash
git add ema_ribbon.py tests/test_ema_ribbon.py docs/specs/ema-ribbon-expansion.md docs/superpowers/plans/2026-10-28-ema-ribbon-expansion.md
git commit -m "feat: add EMA ribbon expansion detector"
```

### Task 2: Multi-market scan integration and TradingView export

**Files:**
- Modify: `sequential.py`
- Modify: `tests/test_ema_ribbon.py`

**Interfaces:**
- Consumes: `ema_ribbon_signal()` and existing daily `(Instrument, DataFrame)` records.
- Produces: daily frame field `ema_ribbon_expansion` containing `scanned_symbols`, `settings`, and `signals`; writes `data/KJ-EMA-Ribbon-Expansion.TXT`.

- [ ] **Step 1: Add a failing integration test for signal metadata and export ordering**

```python
assert item["tradingview_symbol"] == "NASDAQ:TEST"
assert item["signal_type"] == "ema_ribbon_expansion"
assert exported[0] == "NASDAQ:TEST"
```

- [ ] **Step 2: Run the integration test and confirm the absent payload fails**

Run: `python -m unittest tests.test_ema_ribbon -v`
Expected: FAIL because the daily collector has no EMA monitor field.

- [ ] **Step 3: Evaluate the detector inside the existing daily record loop and write the export**

```python
if timeframe.key == "1d":
    ema_event = ema_ribbon_signal(raw)
    if ema_event:
        ema_ribbon_signals.append({"signal_type": "ema_ribbon_expansion", **ema_event})
```

- [ ] **Step 4: Run all Python tests**

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`
Expected: PASS.

- [ ] **Step 5: Commit scan integration**

```bash
git add sequential.py tests/test_ema_ribbon.py
git commit -m "feat: publish EMA expansion scan results"
```

### Task 3: Website monitor panel

**Files:**
- Modify: `index.html`
- Modify: `assets/app.js`
- Modify: `assets/styles.css`
- Modify: `sw.js`
- Test: `tests/test_ema_ribbon_ui.py`

**Interfaces:**
- Consumes: `dailyFrame.ema_ribbon_expansion.signals`.
- Produces: stage and market filters, signal cards, counts, update time, and TradingView TXT download.

- [ ] **Step 1: Add a failing static UI contract test**

```python
assert 'id="ema-ribbon-signals"' in index_html
assert "renderEmaRibbon" in app_js
assert "KJ-EMA-Ribbon-Expansion.TXT" in app_js
```

- [ ] **Step 2: Run the UI contract test and confirm it fails**

Run: `python -m unittest tests.test_ema_ribbon_ui -v`
Expected: FAIL because the panel is not present.

- [ ] **Step 3: Add semantic markup, cards, filtering, and responsive styling**

```javascript
const signals = monitor.signals.filter((signal) => stage === "all" || signal.stage === stage);
elements.emaRibbonSignals.replaceChildren(...signals.map(emaRibbonCard));
```

- [ ] **Step 4: Run Python and JavaScript export tests**

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`
Expected: PASS.

Run: `node --test tests/test_line_reclaim_export.mjs`
Expected: PASS.

- [ ] **Step 5: Commit the website panel**

```bash
git add index.html assets/app.js assets/styles.css sw.js tests/test_ema_ribbon_ui.py
git commit -m "feat: show EMA expansion monitor on radar"
```

### Task 4: Scheduled monitoring documentation and release verification

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/scan-and-deploy.yml`

**Interfaces:**
- Consumes: existing `python sequential.py` Actions step.
- Produces: documented EMA rule and a workflow smoke test that runs the test suite before deployment.

- [ ] **Step 1: Add the EMA monitor description, exact thresholds, and no-repaint opening rule to README**

```markdown
- EMA 五線擴展雷達：日線 EMA 9／21／50／150／200 先壓縮至 3% 內，再形成連續三根多頭排列與擴張。
```

- [ ] **Step 2: Add a workflow test step before data refresh**

```yaml
- name: Run scanner tests
  run: python -m unittest discover -s tests -p 'test_*.py' -v
```

- [ ] **Step 3: Keep the workflow dependency-light**

Run: confirm the workflow uses Python's standard-library `unittest`, so no test-only package is required in `requirements.txt`.

- [ ] **Step 4: Run the complete local verification**

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`
Expected: PASS.

Run: `node --test tests/test_line_reclaim_export.mjs`
Expected: PASS.

- [ ] **Step 5: Commit documentation and workflow protection**

```bash
git add README.md .github/workflows/scan-and-deploy.yml
git commit -m "ci: verify EMA monitor before deploy"
```

