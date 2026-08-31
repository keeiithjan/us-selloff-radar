# Current-Bar Opening Line Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Only label an opening white/orange reclaim when the opening price is above that same daily bar's displayed line.

**Architecture:** `daily_line_reclaim_event` will continue to require a prior unreclaimed real-body breakdown, but will compare today's open to the white or orange value calculated for today's bar.  The Pine screener will use the same same-bar baseline for its opening-reclaim and next-open filters.  A regression test will reproduce an opening that is above yesterday's orange line but below today's orange line, which must not enter the live opening list.

**Tech Stack:** Python 3, pandas, unittest, TradingView Pine Script v5, GitHub Actions/GitHub Pages.

**Spec:** Codex user request on 2026-08-31: opening reclaim must compare with the current bar's white/orange line; exclude 南亞科 when its open is below the orange line displayed for the current bar.

## Global Constraints

- A signal still requires an earlier black real-body break of the same line.
- The live left panel only receives current-session opening-reclaim events.
- `open > line` is strict; an equal opening is not a reclaim.
- Preserve the existing first-body-reclaim behavior and its break-bar count.
- Supply the user the entire updated Pine source after verification.

---

### Task 1: Lock the current-bar baseline with a regression test

**Files:**
- Modify: `tests/test_daily_line_reclaims.py`

**Interfaces:**
- Consumes: `daily_line_reclaim_event(frame: pd.DataFrame) -> dict[str, object] | None`
- Produces: a regression assertion that a same-day opening below `current_orange` has no `"橙線"` in `opening_reclaim_lines`.

- [ ] **Step 1: Write the failing test**

```python
def test_opening_reclaim_uses_current_bar_orange_line(self) -> None:
    frame = base_frame()
    # Seed a real orange-line break on the previous completed bar.
    frame.iloc[-2, frame.columns.get_loc("Open")] = 104.0
    frame.iloc[-2, frame.columns.get_loc("Close")] = 100.5
    # Today opens above yesterday's orange line but below today's line.
    frame.iloc[-1, frame.columns.get_loc("Open")] = 101.0
    frame.iloc[-1, frame.columns.get_loc("High")] = 105.0
    frame.iloc[-1, frame.columns.get_loc("Low")] = 100.0
    frame.iloc[-1, frame.columns.get_loc("Close")] = 101.0

    event = daily_line_reclaim_event(frame)

    self.assertIsNone(event)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_daily_line_reclaims.py`

Expected: the new test fails because `daily_line_reclaim_event` compares `current_open` to `previous_orange`.

- [ ] **Step 3: Adjust the fixture after inspecting its computed current orange value**

```python
event = daily_line_reclaim_event(frame)
self.assertNotIn("橙線", event["opening_reclaim_lines"] if event else [])
```

Use a fixture whose prior break remains pending and whose `current_open` is strictly below the computed `current_orange`; do not mock the indicator calculation.

- [ ] **Step 4: Run test to verify the regression condition is represented**

Run: `python -m unittest tests/test_daily_line_reclaims.py`

Expected: FAIL before Task 2, with `"橙線"` incorrectly present.

- [ ] **Step 5: Commit**

```bash
git add tests/test_daily_line_reclaims.py
git commit -m "test: cover current-bar opening line baseline"
```

### Task 2: Correct the website scanner's opening-reclaim comparison

**Files:**
- Modify: `sequential.py:890-1051`
- Test: `tests/test_daily_line_reclaims.py`

**Interfaces:**
- Consumes: `current_open`, `current_white`, `current_orange` and pending break positions calculated in `daily_line_reclaim_event`.
- Produces: `opening_reclaim_lines: list[str]` populated only when `current_open > current_white` or `current_open > current_orange`, respectively.

- [ ] **Step 1: Replace the two previous-bar comparisons**

```python
if white_opening_break_position is not None and current_open > current_white:
    opening_lines.append("白線")
if orange_opening_break_position is not None and current_open > current_orange:
    opening_lines.append("橙線")
```

- [ ] **Step 2: Update the opening-reclaim docstring**

```python
Opening reclaim uses the current bar's line value, so a symbol must open
above the line visible on that bar rather than only above yesterday's line.
```

- [ ] **Step 3: Run all scanner tests**

Run: `python -m unittest tests/test_daily_line_reclaims.py`

Expected: PASS with all existing first-body and pending-break tests unchanged.

- [ ] **Step 4: Commit**

```bash
git add sequential.py tests/test_daily_line_reclaims.py
git commit -m "fix: compare opening reclaim against current line"
```

### Task 3: Make the Pine screener use the same baseline

**Files:**
- Modify: `outputs/AI Momentum 白線橙線跌破站回 Screener 修正版.pine`

**Interfaces:**
- Consumes: `chartWhite`, `orangeLine`, `open`, prior real-body breakdown state.
- Produces: daily opening-reclaim conditions that require `open > chartWhite` or `open > orangeLine` on the current bar.

- [ ] **Step 1: Define pending orange opening-break state**

```pine
var bool pendingOrangeOpeningBreak = false
orangeOpenReclaimCondition =
     timeframe.isdaily and
     pendingOrangeOpeningBreak and
     open > orangeLine
```

- [ ] **Step 2: Change white and next-open comparisons to the same bar**

```pine
whiteOpenReclaimCondition =
     enableWhiteOpenReclaim and
     timeframe.isdaily and
     pendingWhiteOpeningBreak and
     open > chartWhite

nextOpenAboveWhiteSignal = timeframe.isdaily and whiteBodyBreakSignal[1] and open > chartWhite
nextOpenAboveOrangeSignal = timeframe.isdaily and orangeBodyBreakSignal[1] and open > orangeLine
```

- [ ] **Step 3: Wire orange opening reclaim into signal, pending-state clear, filters, plot, and alert**

```pine
if orangeOpenReclaimCondition
    orangeReclaimSignal := true
```

Mirror white's pending-state lifecycle for orange so the condition cannot be true without a preceding orange real-body break.

- [ ] **Step 4: Inspect the full Pine source for remaining `[1]` opening baseline comparisons**

Run: `rg -n "open > .*\[1\]" "outputs/AI Momentum 白線橙線跌破站回 Screener 修正版.pine"`

Expected: no opening-reclaim comparison remains against a prior-bar line.

- [ ] **Step 5: Commit**

```bash
git add "../outputs/AI Momentum 白線橙線跌破站回 Screener 修正版.pine"
git commit -m "fix: align Pine opening reclaim with current line"
```

### Task 4: Publish and confirm the offending live record is removed

**Files:**
- Modify: repository tracked source files from Tasks 1-2

**Interfaces:**
- Consumes: GitHub Actions deployment generated from `main`.
- Produces: live `/data/sequential.json` that no longer labels a symbol as an opening orange reclaim when `open_price <= current_orange`.

- [ ] **Step 1: Inspect staged changes and test status**

Run: `git diff --check; python -m unittest tests/test_daily_line_reclaims.py`

Expected: no whitespace errors and all tests pass.

- [ ] **Step 2: Push the scanner correction**

```bash
git push origin main
```

- [ ] **Step 3: Wait for GitHub Actions Pages deployment**

Run: `gh run list --workflow scan-and-deploy.yml --limit 1`

Expected: the latest workflow reaches `completed success`.

- [ ] **Step 4: Inspect the live JSON record for TWSE:2408**

```powershell
$payload = curl.exe --silent "https://keeiithjan.github.io/us-selloff-radar/data/sequential.json" | ConvertFrom-Json
$daily = $payload.timeframes | Where-Object { $_.key -eq "1d" }
$daily.daily_line_reclaims.signals | Where-Object { $_.symbol -eq "2408" } | ConvertTo-Json -Depth 8
```

Expected: it is absent from `opening_reclaim_lines` while its opening price is below its current orange line.

- [ ] **Step 5: Commit any deployment-facing cache/version changes, if needed**

```bash
git add index.html sw.js
git commit -m "chore: refresh opening reclaim client cache"
```
