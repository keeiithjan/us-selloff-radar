# Confirmed Daily Reclaim Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Taiwan and US opening reclaims on the left as soon as their daily market opens, while adding names to the right only after the daily bar is confirmed at the market close.

**Architecture:** The scanner retains prior real-body breaks and evaluates an opening reclaim on the new live daily bar. It will suppress a current live bar's first-body-reclaim event, then allow that event only after the market session closes. The scanner writes an explicit confirmed status into JSON, which the right panel requires before displaying a name.

**Tech Stack:** Python 3, pandas, unittest, vanilla JavaScript, GitHub Actions, GitHub Pages.

**Spec:** Codex user request on 2026-08-31: Taiwan and US names with an earlier real-body break must enter the GitHub Pages left panel on an above-line open; the right panel must list only confirmed daily reclaims.

## Global Constraints

- Left panel requires a current daily bar, live market, prior unreclaimed real-body break, and open strictly above the opening baseline.
- Right panel requires a first valid body reclaim after the daily bar has closed.
- Taiwan session is 09:00–13:30 Asia/Taipei; US session is 09:30–16:00 America/New_York.
- Browser polling stays at 15 seconds; GitHub Actions creates the published snapshot.
- An intraday body reclaim may never display as confirmed.

---

### Task 1: Test and gate live first-body reclaims

**Files:**
- Modify: `sequential.py:890-1071`
- Modify: `tests/test_daily_line_reclaims.py`

**Interfaces:**
- Consumes: `daily_line_reclaim_event(frame, allow_current_body_reclaim: bool)`.
- Produces: no `first_reclaim_lines` from a current live daily bar when the parameter is false.

- [ ] **Step 1: Add a failing live-bar test**

```python
event = daily_line_reclaim_event(frame, allow_current_body_reclaim=False)
self.assertIsNone(event)
```

- [ ] **Step 2: Run it before implementation**

Run: `python -m unittest tests/test_daily_line_reclaims.py`

Expected: FAIL because the live final bar is returned as `first_reclaim_lines`.

- [ ] **Step 3: Add the explicit keyword argument and skip a live final position**

```python
def daily_line_reclaim_event(
    frame: pd.DataFrame,
    *,
    allow_current_body_reclaim: bool = True,
) -> dict[str, object] | None:
```

```python
if position == last_position and not allow_current_body_reclaim:
    continue
```

- [ ] **Step 4: Re-run all daily-line tests**

Run: `python -m unittest tests/test_daily_line_reclaims.py`

Expected: PASS.

### Task 2: Compute market state and write a confirmation field

**Files:**
- Modify: `sequential.py:1736-1765`

**Interfaces:**
- Consumes: `is_current_daily_bar(index, session, now)` and `session_is_live(session, now)`.
- Produces: `first_reclaim_confirmed: bool` on every line-reclaim signal.

- [ ] **Step 1: Determine state before calling the event function**

```python
event_index = raw.index[-1]
current_daily_bar = is_current_daily_bar(event_index, instrument.session, now)
market_live = current_daily_bar and session_is_live(instrument.session, now)
live_event = daily_line_reclaim_event(raw, allow_current_body_reclaim=not market_live)
```

- [ ] **Step 2: Write the JSON state**

```python
"is_live_session": market_live,
"first_reclaim_confirmed": bool(live_event.get("first_reclaim_lines")) and not market_live,
```

- [ ] **Step 3: Preserve opening events during Taiwan and US live sessions**

Leave `opening_reclaim_lines` available when `market_live` is true.

### Task 3: Present confirmed names and reduce scan latency

**Files:**
- Modify: `assets/app.js:334-510`
- Modify: `index.html:18-80`
- Modify: `.github/workflows/scan-and-deploy.yml:7-12`
- Modify: `sw.js:4-11`

**Interfaces:**
- Consumes: `first_reclaim_confirmed`.
- Produces: a right-side `CONFIRMED` list and a five-minute source refresh cadence.

- [ ] **Step 1: Require confirmation in the right panel filter**

```javascript
const latestFirstSignals = signals.filter((signal) => (
  lineNames(signal, "first_reclaim_lines").length > 0
  && signal.first_reclaim_confirmed === true
));
```

- [ ] **Step 2: Label right-side cards**

```javascript
live.className = `line-reclaim-session ${mode === "first" ? "closed" : signal.is_live_session ? "live" : "closed"}`;
live.textContent = mode === "first" ? "CONFIRMED" : signal.is_live_session ? "LIVE" : "最新日K";
```

- [ ] **Step 3: Clarify right-panel copy**

```html
右側只會在各市場日線收盤確認後，加入第一根有效實體站回名單。
```

- [ ] **Step 4: Use a five-minute schedule and bump the cached app shell**

```yaml
- cron: "2,7,12,17,22,27,32,37,42,47,52,57 * * * 1-5"
```

Change `line-reclaim6` to `line-reclaim7` and `kj-radar-shell-v20` to `kj-radar-shell-v21`.

### Task 4: Verify and publish

**Files:**
- Test: `tests/test_daily_line_reclaims.py`

**Interfaces:**
- Consumes: scanner, client, and workflow changes.
- Produces: a deployable Pages snapshot.

- [ ] **Step 1: Run checks**

Run: `python -m unittest tests/test_daily_line_reclaims.py`

Run: `node --check assets/app.js`

Run: `git diff --check`

Expected: all checks pass with no whitespace errors.

- [ ] **Step 2: Commit and push after publish approval**

```bash
git add sequential.py tests/test_daily_line_reclaims.py assets/app.js index.html sw.js .github/workflows/scan-and-deploy.yml
git commit -m "feat: publish confirmed daily reclaim status"
git push origin main
```
