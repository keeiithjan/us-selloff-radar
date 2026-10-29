# Sticky Mode Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sticky homepage selector that jumps directly to each monitoring mode and follows manual scrolling.

**Architecture:** Add stable section IDs and one native select to `index.html`, keep navigation behavior in `assets/app.js`, and isolate sticky/responsive presentation in `assets/styles.css`. A UI contract test protects the six targets, navigation wiring, and PWA cache revision.

**Tech Stack:** Semantic HTML, CSS sticky positioning, browser DOM APIs, Python `unittest`, Node syntax validation

**Spec:** `docs/specs/mode-selector.md`

## Global Constraints

- The selector must remain visible while scrolling on desktop and mobile.
- It must navigate without changing any scanner data or filtering behavior.
- Reduced-motion users must not receive smooth scrolling.
- The PWA cache must be revised with the same asset query string used by `index.html`.

---

### Task 1: Mode Selector Markup and Contract

**Files:**
- Create: `tests/test_mode_selector_ui.py`
- Modify: `index.html`

**Interfaces:**
- Consumes: Existing homepage sections and their heading labels.
- Produces: `#mode-selector` whose option values match six `.mode-target` section IDs.

- [ ] **Step 1: Write the failing UI contract test**

```python
self.assertIn('id="mode-selector"', index_html)
for target in ("line-reclaim-command", "big-black-command", "ema-ribbon-command", "market-pulse-mode", "weekly-reclaim-monitor", "td-monitor"):
    self.assertIn(f'value="{target}"', index_html)
    self.assertIn(f'id="{target}"', index_html)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python -m unittest tests.test_mode_selector_ui -v`
Expected: FAIL because `#mode-selector` does not exist.

- [ ] **Step 3: Add the selector and stable target IDs**

```html
<nav class="mode-switcher" aria-label="監控模式選擇">
  <label for="mode-selector"><span>模式選擇</span><select id="mode-selector">…</select></label>
</nav>
<section id="line-reclaim-command" class="line-reclaim-command mode-target">…</section>
```

- [ ] **Step 4: Run the contract test and confirm markup passes**

Run: `python -m unittest tests.test_mode_selector_ui -v`
Expected: The markup assertions pass; behavior and version assertions still fail.

### Task 2: Sticky Navigation Behavior and Presentation

**Files:**
- Modify: `assets/app.js`
- Modify: `assets/styles.css`
- Modify: `index.html`
- Modify: `sw.js`
- Test: `tests/test_mode_selector_ui.py`

**Interfaces:**
- Consumes: `#mode-selector` and `.mode-target` elements.
- Produces: `configureModeSelector()` and `syncModeSelectorToScroll()`; bundle version `20261028-mode-selector1`; shell cache `kj-radar-shell-v32`.

- [ ] **Step 1: Add change navigation and scroll synchronization**

```javascript
function navigateToMode(targetId) {
  const target = document.getElementById(targetId);
  if (!target) return;
  target.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth", block: "start" });
  window.history.replaceState(null, "", `#${targetId}`);
}
```

- [ ] **Step 2: Add sticky and responsive CSS**

```css
.mode-switcher { position: sticky; top: 10px; z-index: 50; }
.mode-target { scroll-margin-top: 92px; }
```

- [ ] **Step 3: Rev the PWA shell and asset query strings**

```javascript
const CACHE_NAME = "kj-radar-shell-v32";
```

- [ ] **Step 4: Run complete verification**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS.

Run: `node --check assets/app.js`
Expected: exit 0.

Run: `node --test tests/test_line_reclaim_export.mjs`
Expected: PASS.

- [ ] **Step 5: Commit and deploy**

```bash
git add index.html assets/app.js assets/styles.css sw.js tests/test_mode_selector_ui.py docs/specs/mode-selector.md docs/superpowers/plans/2026-10-28-mode-selector.md
git commit -m "feat: add sticky monitor mode selector"
git push origin main
```
