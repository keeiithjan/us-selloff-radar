# Temporary Intrabar Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show real-time temporary white/orange body-break and body-reclaim signals before a daily bar closes without allowing them to become confirmed state or notifications.

**Architecture:** The Pine indicator will calculate preview-only conditions during a live, unconfirmed daily bar.  A preview breakdown uses the normal real-body crossing rule.  A preview reclaim also requires a previously confirmed, unreclaimed breakdown of the same line.  These conditions appear in separate scanner filters, data-window outputs, and chart labels; no persistent pending state, official signal, or alert references them.

**Tech Stack:** TradingView Pine Script v5; `jdehorty/KernelFunctions/2`.

**Spec:** Codex user request on 2026-08-31: add temporary unclosed-bar body-break and body-reclaim signals.

## Global Constraints

- Temporary signals require `barstate.isrealtime and not barstate.isconfirmed`.
- A temporary reclaim requires a prior confirmed black real-body break of the same line.
- Temporary signals disappear on close if the completed candle does not meet the confirmed rule.
- Temporary signals do not mutate pending-break variables or send notifications.
- Supply the user the full updated Pine source.

---

### Task 1: Add independent temporary signal conditions

**Files:**
- Modify: `outputs/AI Momentum 白線橙線跌破站回 Screener 修正版.pine:120-190`

**Interfaces:**
- Consumes: `whiteBodyCrossDown`, `orangeBodyCrossDown`, `whiteReclaimCondition`, `orangeReclaimCondition`, `pendingWhiteOpeningBreak`, `pendingOrangeOpeningBreak`.
- Produces: `whiteBodyBreakPreview`, `orangeBodyBreakPreview`, `whiteReclaimPreview`, `orangeReclaimPreview`, and aggregate preview booleans.

- [ ] **Step 1: Add the user control and preview time window**

```pine
showTemporaryIntrabarSignals = input.bool(
     true,
     "顯示未收盤暫時跌破／站回",
     group = "圖表顯示")

temporarySignalWindow =
     showTemporaryIntrabarSignals and
     confirmedBarsOnly and
     timeframe.isdaily and
     barstate.isrealtime and
     not barstate.isconfirmed
```

- [ ] **Step 2: Add the four temporary conditions**

```pine
whiteBodyBreakPreview = temporarySignalWindow and whiteBodyCrossDown
orangeBodyBreakPreview = temporarySignalWindow and orangeBodyCrossDown
whiteReclaimPreview = temporarySignalWindow and pendingWhiteOpeningBreak and whiteReclaimCondition
orangeReclaimPreview = temporarySignalWindow and pendingOrangeOpeningBreak and orangeReclaimCondition
```

- [ ] **Step 3: Verify no persistent-state assignment uses a preview condition**

Run: `rg -n "Preview.*:=|pending.*Preview|alert.*Preview" "outputs/AI Momentum 白線橙線跌破站回 Screener 修正版.pine"`

Expected: no state assignment or notification uses a preview condition.

### Task 2: Expose previews to Pine Screener and chart users

**Files:**
- Modify: `outputs/AI Momentum 白線橙線跌破站回 Screener 修正版.pine:55-400`

**Interfaces:**
- Consumes: aggregate preview booleans from Task 1.
- Produces: five `scanStage` selections, five data-window plots, and four temporary `plotshape` labels.

- [ ] **Step 1: Add temporary scan-stage options and switch branches**

```pine
"未收盤暫時白線實體跌破", "未收盤暫時橙線實體跌破",
"未收盤暫時白線實體站回", "未收盤暫時橙線實體站回",
"未收盤暫時跌破或站回"
```

```pine
"未收盤暫時白線實體跌破" => whiteBodyBreakPreview
"未收盤暫時橙線實體跌破" => orangeBodyBreakPreview
"未收盤暫時白線實體站回" => whiteReclaimPreview
"未收盤暫時橙線實體站回" => orangeReclaimPreview
"未收盤暫時跌破或站回" => temporaryPreviewSignal
```

- [ ] **Step 2: Add data-window output plots after the existing outputs**

```pine
plot(whiteBodyBreakPreview ? 1 : 0, "未收盤暫時實體跌破白線", display = display.data_window)
plot(orangeBodyBreakPreview ? 1 : 0, "未收盤暫時實體跌破橙色線", display = display.data_window)
plot(whiteReclaimPreview ? 1 : 0, "未收盤暫時實體站回白線", display = display.data_window)
plot(orangeReclaimPreview ? 1 : 0, "未收盤暫時實體站回橙色線", display = display.data_window)
plot(temporaryPreviewSignal ? 1 : 0, "未收盤暫時跌破或站回", display = display.data_window)
```

- [ ] **Step 3: Add temporary chart labels that do not overlap the confirmed labels**

```pine
plotshape(showMarks and whiteBodyBreakPreview, title = "白線暫時實體跌破", style = shape.labeldown, location = location.abovebar, color = color.gray, textcolor = color.white, text = "暫破白", size = size.tiny)
plotshape(showMarks and orangeBodyBreakPreview, title = "橙線暫時實體跌破", style = shape.labeldown, location = location.abovebar, color = color.yellow, textcolor = color.black, text = "暫破橙", size = size.tiny)
plotshape(showMarks and whiteReclaimPreview, title = "白線暫時實體站回", style = shape.labelup, location = location.belowbar, color = color.gray, textcolor = color.white, text = "暫回白", size = size.tiny)
plotshape(showMarks and orangeReclaimPreview, title = "橙線暫時實體站回", style = shape.labelup, location = location.belowbar, color = color.yellow, textcolor = color.black, text = "暫回橙", size = size.tiny)
```

### Task 3: Verify static safety and hand off full code

**Files:**
- Modify: `outputs/AI Momentum 白線橙線跌破站回 Screener 修正版.pine`

**Interfaces:**
- Consumes: complete Pine source after Tasks 1-2.
- Produces: a self-contained Pine v5 script where previews cannot generate a confirmed alert.

- [ ] **Step 1: Inspect preview references**

Run: `rg -n "Preview|temporarySignalWindow|暫時" "outputs/AI Momentum 白線橙線跌破站回 Screener 修正版.pine"`

Expected: preview references occur only in definitions, filter selection, data-window plots, and chart shapes.

- [ ] **Step 2: Inspect official alerts**

Run: `rg -n "alert\(|alertcondition" "outputs/AI Momentum 白線橙線跌破站回 Screener 修正版.pine"`

Expected: no alert condition references `Preview` or `temporaryPreviewSignal`.

- [ ] **Step 3: Provide the complete script**

Paste the full file to the user, explaining that gray/yellow labels are temporary and disappear unless confirmed at the close.
