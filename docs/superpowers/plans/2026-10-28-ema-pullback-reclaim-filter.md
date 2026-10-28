# EMA Pullback Reclaim Filter Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the EMA monitor so its main list contains only recent five-line compression structures that suffered a real-body fast-EMA break and immediately reclaimed EMA9 at the next open without excessive divergence.

**Architecture:** Tighten the pure detector before metadata reaches the collector, so JSON, website cards, and the TradingView export all share one source of truth. Expose actual alignment streak and compression age for auditing, then simplify the website copy because every surviving signal is an opening reclaim.

**Tech Stack:** Python 3.12, pandas, standard-library unittest, vanilla JavaScript, HTML/CSS, GitHub Actions, GitHub Pages

**Spec:** `docs/specs/ema-ribbon-expansion.md`

## Global Constraints

- EMA lengths remain exactly 9, 21, 50, 150, and 200 daily bars.
- Prior five-line compression is `spread_pct <= 3.0` and must have occurred no more than 20 bars ago.
- Current five-line spread must be `<= 6.0%`.
- Current bullish-alignment streak must be between 3 and 15 bars inclusive.
- A signal requires the immediately previous bearish real body to cross below EMA9 or EMA21 and the current open to exceed the previous completed EMA9.
- Current close must never be used to calculate the opening-reclaim threshold.

---

### Task 1: Reject mature and non-reclaim structures in the pure detector

**Files:**
- Modify: `ema_ribbon.py`
- Modify: `tests/test_ema_ribbon.py`

**Interfaces:**
- Consumes: `ema_ribbon_signal(frame: pd.DataFrame, settings: EmaRibbonSettings) -> dict[str, object] | None`.
- Produces: only `open_reclaim` dictionaries containing `alignment_streak`, `compression_bars_ago`, `current_spread_pct`, and `fast_break_lines`.

- [ ] **Step 1: Write failing boundary tests**

```python
self.assertIsNone(ema_ribbon_signal(frame_without_body_break))
self.assertIsNone(ema_ribbon_signal(frame_with_spread_above_six_pct))
self.assertIsNone(ema_ribbon_signal(frame_with_alignment_streak_above_fifteen))
self.assertIsNone(ema_ribbon_signal(frame_with_compression_more_than_twenty_bars_ago))
```

- [ ] **Step 2: Run the focused tests and confirm the old expansion-watch behavior fails**

Run: `python -m unittest tests.test_ema_ribbon -v`
Expected: FAIL because the current detector still returns `expansion_watch` and has no mature-trend caps.

- [ ] **Step 3: Add exact streak, compression-age, spread, and mandatory-reclaim gates**

```python
if not fast_break_lines or not open_above_previous_ema9:
    return None
if alignment_streak > settings.maximum_alignment_bars:
    return None
if compression_bars_ago > settings.maximum_compression_age_bars:
    return None
if float(latest["ema_spread_pct"]) > settings.maximum_current_spread_pct:
    return None
```

- [ ] **Step 4: Run the focused tests**

Run: `python -m unittest tests.test_ema_ribbon -v`
Expected: PASS.

- [ ] **Step 5: Commit the detector correction**

```bash
git add ema_ribbon.py tests/test_ema_ribbon.py docs/specs/ema-ribbon-expansion.md docs/superpowers/plans/2026-10-28-ema-pullback-reclaim-filter.md
git commit -m "fix: restrict EMA radar to fresh opening reclaims"
```

### Task 2: Align export and website semantics

**Files:**
- Modify: `sequential.py`
- Modify: `index.html`
- Modify: `assets/app.js`
- Modify: `sw.js`
- Modify: `README.md`
- Modify: `tests/test_ema_ribbon.py`
- Modify: `tests/test_ema_ribbon_ui.py`

**Interfaces:**
- Consumes: detector output where every item has `stage == "open_reclaim"`.
- Produces: a reclaim-only JSON list, reclaim-only TradingView TXT, and cards that show actual streak and compression age.

- [ ] **Step 1: Update tests to require reclaim-only exports and corrected copy**

```python
self.assertNotIn('data-ema-stage="expansion_watch"', index_html)
self.assertIn("實際連續", app_js)
self.assertIn("距交纏", app_js)
```

- [ ] **Step 2: Run UI and export tests and confirm the old stage filter fails**

Run: `python -m unittest tests.test_ema_ribbon tests.test_ema_ribbon_ui -v`
Expected: FAIL because the website still offers an expansion-watch stage.

- [ ] **Step 3: Remove expansion-watch controls and render audit metrics**

```javascript
const metricValues = [
  ["多頭排列", `${Number(signal.alignment_streak)} 根`],
  ["距交纏", `${Number(signal.compression_bars_ago)} 根`],
];
```

- [ ] **Step 4: Bump the PWA bundle version and document the corrected thresholds**

```javascript
const CACHE_NAME = "kj-radar-shell-v31";
```

- [ ] **Step 5: Run complete verification**

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`
Expected: PASS.

Run: `node --check assets/app.js`
Expected: no output and exit code 0.

Run: `node --test tests/test_line_reclaim_export.mjs`
Expected: PASS.

- [ ] **Step 6: Commit UI and documentation alignment**

```bash
git add sequential.py index.html assets/app.js sw.js README.md tests/test_ema_ribbon.py tests/test_ema_ribbon_ui.py
git commit -m "fix: present EMA radar as fresh pullback reclaims"
```

