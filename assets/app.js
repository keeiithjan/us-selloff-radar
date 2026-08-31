const elements = {
  refresh: document.querySelector("#refresh"),
  enableLineAlerts: document.querySelector("#enable-line-alerts"),
  lineReclaimUpdated: document.querySelector("#line-reclaim-updated"),
  lineReclaimScanCount: document.querySelector("#line-reclaim-scan-count"),
  lineReclaimNotice: document.querySelector("#line-reclaim-notice"),
  openingReclaimCount: document.querySelector("#opening-reclaim-count"),
  firstReclaimCount: document.querySelector("#first-reclaim-count"),
  openingReclaimTitle: document.querySelector("#opening-reclaim-title"),
  firstReclaimTitle: document.querySelector("#first-reclaim-title"),
  openingReclaimSignals: document.querySelector("#opening-reclaim-signals"),
  firstReclaimSignals: document.querySelector("#first-reclaim-signals"),
  lineReclaimTimeframeFilters: [...document.querySelectorAll("[data-reclaim-timeframe]")],
  lineReclaimLineFilters: [...document.querySelectorAll("[data-reclaim-line]")],
  lineReclaimMarketFilters: [...document.querySelectorAll("[data-reclaim-market]")],
  installApp: document.querySelector("#install-app"),
  installAppNote: document.querySelector("#install-app-note"),
  systemStatus: document.querySelector("#system-status"),
  systemStatusTitle: document.querySelector("#system-status-title"),
  systemStatusDetail: document.querySelector("#system-status-detail"),
  systemStatusLog: document.querySelector("#system-status-log"),
  sequentialFrames: document.querySelector("#sequential-frames"),
  sequentialUpdated: document.querySelector("#sequential-updated"),
  sequentialSource: document.querySelector("#sequential-source"),
  marketFilters: [...document.querySelectorAll('input[name="market-filter"]')],
  sequentialSort: document.querySelector("#sequential-sort"),
  sequentialSide: document.querySelector("#sequential-side"),
  sequentialMomentum: document.querySelector("#sequential-momentum"),
  downloadTradingViewList: document.querySelector("#download-tradingview-list"),
  tradingViewExportNote: document.querySelector("#tradingview-export-note"),
  trendReclaimFrames: document.querySelector("#trend-reclaim-frames"),
  weeklyReclaimSignals: document.querySelector("#weekly-reclaim-signals"),
  weeklyReclaimFilter: document.querySelector("#weekly-reclaim-filter"),
  weeklyReclaimExportNote: document.querySelector("#weekly-reclaim-export-note"),
  downloadWeeklyTradingViewList: document.querySelector("#download-weekly-tradingview-list"),
  marketPulseUpdated: document.querySelector("#market-pulse-updated"),
  futuresStrip: document.querySelector("#futures-strip"),
  scanProgress: document.querySelector("#scan-progress"),
  scanProgressState: document.querySelector("#scan-progress-state"),
  scanProgressTrack: document.querySelector(".scan-progress-track"),
  scanProgressFill: document.querySelector("#scan-progress-fill"),
  scanProgressPercent: document.querySelector("#scan-progress-percent"),
  scanProgressUpdated: document.querySelector("#scan-progress-updated"),
};

let sequentialPayload = null;
const lineReclaimFilterState = { timeframe: "1d", line: "all", market: "all" };
let marketUpdatedAt = null;
let marketAgeTimer = null;
let deferredInstallPrompt = null;
const LINE_ALERT_STORAGE_KEY = "kj-radar-daily-open-reclaim-notified-v1";
const ACTIONS_PAGE_URL = "https://github.com/keeiithjan/us-selloff-radar/actions";
const ACTIONS_RUNS_URL = "https://api.github.com/repos/keeiithjan/us-selloff-radar/actions/workflows/scan-and-deploy.yml/runs?per_page=1";
const ACTIONS_POLL_INTERVAL_MS = 5 * 60 * 1000;
let latestWorkflowResult = { run: null, error: null, checkedAt: 0 };
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const motionState = {
  futures: new Map(),
  movers: new Map(),
  hasMarket: false,
};

function formatCurrency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function formatCompactCurrency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(Number(value));
}

function formatMarketPrice(value, currency) {
  const supported = new Set(["USD", "TWD", "JPY", "KRW"]);
  const code = supported.has(currency) ? currency : "USD";
  const locales = { TWD: "zh-TW", JPY: "ja-JP", KRW: "ko-KR", USD: "en-US" };
  return new Intl.NumberFormat(locales[code], {
    style: "currency",
    currency: code,
    maximumFractionDigits: ["TWD", "JPY", "KRW"].includes(code) ? 0 : 2,
  }).format(Number(value));
}

function formatSignalPrice(signal) {
  const value = Number(signal?.last_price);
  if (!Number.isFinite(value)) return "—";
  if (
    signal?.market === "Pepperstone CFD" &&
    String(signal?.product_category || signal?.industry || "").includes("外匯")
  ) {
    return value.toLocaleString("en-US", {
      minimumFractionDigits: value >= 20 ? 3 : 5,
      maximumFractionDigits: value >= 20 ? 3 : 5,
    });
  }
  return formatCurrency(value);
}

function formatSigned(value, digits = 2) {
  const number = Number(value);
  const sign = number > 0 ? "+" : "";
  return `${sign}${number.toFixed(digits)}`;
}

function numberChanged(previous, next) {
  const before = Number(previous);
  const after = Number(next);
  if (!Number.isFinite(before) || !Number.isFinite(after)) return false;
  return Math.abs(before - after) > Math.max(0.000001, Math.abs(after) * 0.0000001);
}

function quoteMotion(previous, item, initial) {
  if (!previous) return { enter: true, isNew: !initial, isUpdated: false };
  return {
    enter: numberChanged(previous.last_price, item.last_price) || numberChanged(previous.change_pct, item.change_pct),
    isNew: false,
    isUpdated: numberChanged(previous.last_price, item.last_price) || numberChanged(previous.change_pct, item.change_pct),
  };
}

function quoteSnapshot(items, key) {
  return new Map(items.map((item) => [String(item[key] || ""), item]));
}

function animateNumber(node, from, to, formatter) {
  const startValue = Number(from);
  const endValue = Number(to);
  if (
    reducedMotion.matches ||
    !Number.isFinite(startValue) ||
    !Number.isFinite(endValue) ||
    !numberChanged(startValue, endValue)
  ) {
    node.textContent = formatter(endValue);
    return;
  }
  const startedAt = performance.now();
  const duration = 680;
  node.classList.add("is-ticking");
  const tick = (now) => {
    const progress = Math.min(1, (now - startedAt) / duration);
    const eased = 1 - (1 - progress) ** 3;
    const distance = Math.abs(endValue - startValue) || Math.max(Math.abs(endValue) * 0.012, 0.01);
    const flicker = progress < 0.82 ? Math.sin(progress * 48) * distance * (1 - progress) * 0.18 : 0;
    node.textContent = formatter(startValue + (endValue - startValue) * eased + flicker);
    if (progress < 1) {
      window.requestAnimationFrame(tick);
    } else {
      node.textContent = formatter(endValue);
      node.classList.remove("is-ticking");
    }
  };
  window.requestAnimationFrame(tick);
}

function initialNumberStart(value, direction, percentage = false) {
  const target = Number(value);
  if (!Number.isFinite(target)) return target;
  if (percentage) return 0;
  const offset = direction === "down" ? 1.012 : 0.988;
  return target * offset;
}

function formatTaipei(value) {
  return new Intl.DateTimeFormat("zh-TW", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Asia/Taipei",
  }).format(new Date(value));
}

function scanErrors(payload) {
  return Array.isArray(payload?.scan_errors)
    ? payload.scan_errors.map((error) => String(error).trim()).filter(Boolean)
    : [];
}

function workflowStateDetail(run) {
  if (!run) return "GitHub Actions 狀態暫時無法讀取";
  const status = String(run.status || "");
  if (["queued", "requested", "waiting"].includes(status)) return "GitHub Actions 正在等待執行器";
  if (status === "in_progress") return "GitHub Actions 正在掃描並部署最新資料";
  const conclusion = String(run.conclusion || "");
  return {
    success: "GitHub Actions 最近一次執行成功",
    failure: "GitHub Actions 最近一次執行失敗",
    cancelled: "GitHub Actions 最近一次執行已取消",
    timed_out: "GitHub Actions 最近一次執行逾時",
    action_required: "GitHub Actions 需要人工處理",
  }[conclusion] || "GitHub Actions 最近一次執行已結束";
}

function renderSystemStatus(payload, run, workflowError = null) {
  if (!elements.systemStatus) return;
  const errors = scanErrors(payload);
  const updatedAt = payload?.updated_at_utc;
  const updatedAtText = updatedAt ? `資料更新：${formatTaipei(updatedAt)}` : "尚未取得最新資料時間";
  const status = String(run?.status || "");
  const conclusion = String(run?.conclusion || "");
  const running = ["queued", "requested", "waiting", "in_progress"].includes(status);
  const failed = status === "completed" && !["success", "neutral", "skipped"].includes(conclusion);
  const isStale = updatedAt && Number.isFinite(Date.parse(updatedAt))
    && Date.now() - Date.parse(updatedAt) > 100 * 60 * 1000;
  let level = "success";
  let title = "資料掃描正常";
  const details = [updatedAtText];

  if (running) {
    level = "running";
    title = "掃描與部署進行中";
  } else if (failed) {
    level = "error";
    title = "最近一次掃描失敗";
  } else if (errors.length || isStale || workflowError) {
    level = "warning";
    title = errors.length
      ? `掃描完成，但 ${errors.length} 個來源有警告`
      : isStale
        ? "資料更新可能延遲"
        : "資料正常，Actions 狀態暫時無法讀取";
  }

  details.push(workflowStateDetail(run));
  if (errors.length) details.push(`來源警告：${errors.join("、")}`);
  if (workflowError) details.push("可開啟 Actions Log 查看即時執行紀錄");

  elements.systemStatus.className = `system-status is-${level}`;
  elements.systemStatusTitle.textContent = title;
  elements.systemStatusDetail.textContent = details.join("｜");
  if (elements.systemStatusLog) {
    elements.systemStatusLog.href = run?.html_url || ACTIONS_PAGE_URL;
    elements.systemStatusLog.textContent = running ? "查看即時 Actions Log" : "查看 Actions Log";
  }
}

function makeTextPair(label, value) {
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value;
  return [labelNode, valueNode];
}

function makeStat(label, value) {
  const box = document.createElement("div");
  box.className = "stat";
  box.append(...makeTextPair(label, value));
  return box;
}

function tradingViewUrl(item, interval) {
  const symbol = String(item.symbol || "").replace(/[^A-Z0-9.-]/g, "");
  const exchange = String(item.exchange || "NASDAQ").replace(/[^A-Z]/g, "");
  const chartSymbol = item.tradingview_symbol || `${exchange}:${symbol}`;
  const query = new URLSearchParams({ symbol: chartSymbol });
  if (interval) query.set("interval", interval);
  return `https://tw.tradingview.com/chart/?${query.toString()}`;
}

function marketTradingViewUrl(symbol) {
  const query = new URLSearchParams({ symbol: String(symbol || "") });
  query.set("interval", "5");
  return `https://tw.tradingview.com/chart/?${query.toString()}`;
}

function makeTradingViewLink(item, interval) {
  const link = document.createElement("a");
  link.className = "tv-link";
  link.href = tradingViewUrl(item, interval);
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "T";
  link.title = "在 TradingView 開啟圖表";
  link.setAttribute("aria-label", "在 TradingView 開啟圖表");
  return link;
}

function industryText(item) {
  if (typeof item === "string") return `產品分類｜${item}`;
  const product = String(item?.product_category || "").trim();
  const industry = String(item?.industry || "").trim();
  // Old JSON payloads may still contain the former placeholder.  Prefer the
  // exchange-supplied industry until the next complete scan replaces them.
  if (product.startsWith("產業分類：")) return product;
  if (product && !/待建檔|待分類/.test(product)) return `主力產品｜${product}`;
  if (industry) return `產業分類｜${industry}`;
  return "產業分類｜暫無公開分類";
}

function displayMarket(market) {
  return market === "台股個股期貨標的" ? "台股" : (market || "市場");
}

function lineNames(signal, key) {
  return (Array.isArray(signal?.[key]) ? signal[key] : [])
    .map((line) => String(line || "").trim())
    .filter(Boolean);
}

function lineReclaimMarketGroup(signal) {
  const market = displayMarket(signal?.market);
  if (market === "台股") return "taiwan";
  if (market === "美股") return "us";
  return "other";
}

function filteredLineReclaims(signals, field) {
  return signals.filter((signal) => {
    const matchesLine = lineReclaimFilterState.line === "all"
      || lineNames(signal, field).includes(lineReclaimFilterState.line);
    const matchesMarket = lineReclaimFilterState.market === "all"
      || lineReclaimMarketGroup(signal) === lineReclaimFilterState.market;
    return matchesLine && matchesMarket;
  });
}

function updateLineReclaimFilterControls() {
  for (const button of elements.lineReclaimTimeframeFilters) {
    const active = button.dataset.reclaimTimeframe === lineReclaimFilterState.timeframe;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  for (const button of elements.lineReclaimLineFilters) {
    const active = button.dataset.reclaimLine === lineReclaimFilterState.line;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  for (const button of elements.lineReclaimMarketFilters) {
    const active = button.dataset.reclaimMarket === lineReclaimFilterState.market;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

function makeLineReclaimCard(signal, mode) {
  const isWeekly = signal.timeframe_key === "1w";
  const field = mode === "opening" ? "opening_reclaim_lines" : "first_reclaim_lines";
  const lines = lineNames(signal, field);
  const card = document.createElement("article");
  card.className = `line-reclaim-card ${mode}${signal.is_live_session ? " is-live" : ""}`;

  const top = document.createElement("div");
  top.className = "line-reclaim-card-top";
  const identity = document.createElement("div");
  const ticker = document.createElement("h3");
  ticker.textContent = signal.name ? `${signal.symbol} ${signal.name}` : signal.symbol;
  const market = document.createElement("p");
  market.textContent = `${displayMarket(signal.market)} · ${industryText(signal)}`;
  identity.append(ticker, market);
  const live = document.createElement("span");
  const confirmedFirstReclaim = mode === "first" && signal.first_reclaim_confirmed === true;
  live.className = `line-reclaim-session ${mode === "first" ? "closed" : signal.is_live_session ? "live" : "closed"}`;
  live.textContent = confirmedFirstReclaim
    ? "CONFIRMED"
    : signal.is_live_session ? "LIVE" : (isWeekly ? "最新週K" : "最新日K");
  top.append(identity, live);

  const badges = document.createElement("div");
  badges.className = "line-reclaim-badges";
  for (const line of lines) {
    const badge = document.createElement("span");
    badge.className = line === "橙線" ? "orange" : "white";
    badge.textContent = mode === "opening" ? `開盤站回${line}` : `${line}第一根站回`;
    badges.append(badge);
  }

  const quote = document.createElement("div");
  quote.className = "line-reclaim-quote";
  const price = document.createElement("strong");
  price.textContent = formatSignalPrice(signal);
  const change = makeTodayChange(signal.change_pct, isWeekly ? "週內" : "日內");
  quote.append(price);
  if (change) quote.append(change);

  const rule = document.createElement("p");
  rule.className = "line-reclaim-rule";
  const broken = lineNames(signal, "broken_lines").join("＋") || "目標線";
  rule.textContent = mode === "opening"
    ? `先前黑K實體跌破${broken}；${isWeekly ? "本週" : "今日"}開盤高於同一條線的開盤基準值。`
    : `先前黑K實體跌破${broken}；${isWeekly ? "本週" : "今日"}為該次跌破後第一根有效站回K，與開盤位置無關。`;

  const values = document.createElement("p");
  values.className = "line-reclaim-values";
  const openingLines = lines.map((line) => {
    const openingValue = line === "橙線" ? signal.opening_orange : signal.opening_white;
    const currentValue = line === "橙線" ? signal.current_orange : signal.current_white;
    return `${line} ${plainQuote(openingValue ?? currentValue)}`;
  }).join(" ／ ");
  const currentLines = lines.map((line) => `${line} ${plainQuote(line === "橙線" ? signal.current_orange : signal.current_white)}`).join(" ／ ");
  const currentPeriod = isWeekly ? "本週" : "今日";
  values.textContent = mode === "opening"
    ? `${currentPeriod} O ${plainQuote(signal.open_price)}｜開盤基準 ${openingLines}`
    : `${currentPeriod} O ${plainQuote(signal.open_price)} ／ 現價 ${plainQuote(signal.last_price)}｜目前 ${currentLines}`;

  const footer = document.createElement("div");
  footer.className = "line-reclaim-card-footer";
  const time = document.createElement("span");
  time.textContent = signal.bar_time_et || (isWeekly ? "最新週線" : "最新日線");
  footer.append(time, makeTradingViewLink(signal, isWeekly ? "W" : "D"));

  card.append(top, badges, quote, rule, values, footer);
  return card;
}

function renderLineReclaimList(container, signals, mode) {
  if (!container) return;
  if (signals.length === 0) {
    const empty = document.createElement("p");
    empty.className = "line-reclaim-empty";
    const weekly = lineReclaimFilterState.timeframe === "1w";
    empty.textContent = mode === "opening"
      ? `目前沒有開盤中的即時站回訊號；休市時不保留前一${weekly ? "週" : "交易日"}的開盤事件。`
      : `目前沒有位於跌破後第一根有效站回${weekly ? "週K" : "日K"}的標的。`;
    container.replaceChildren(empty);
    return;
  }
  container.replaceChildren(...signals.map((signal) => makeLineReclaimCard(signal, mode)));
}

function notifiedLineAlertKeys() {
  try {
    const value = JSON.parse(localStorage.getItem(LINE_ALERT_STORAGE_KEY) || "[]");
    return new Set(Array.isArray(value) ? value.map(String) : []);
  } catch {
    return new Set();
  }
}

function saveNotifiedLineAlertKeys(keys) {
  try {
    localStorage.setItem(LINE_ALERT_STORAGE_KEY, JSON.stringify([...keys].slice(-250)));
  } catch {
    // Private browsing or locked-down storage should not block rendering.
  }
}

async function showLineReclaimNotification(signal) {
  const isWeekly = signal.timeframe_key === "1w";
  const lines = lineNames(signal, "opening_reclaim_lines").join("＋");
  const title = `${signal.symbol} ${isWeekly ? "週線" : "日線"}開盤站回${lines}`;
  const body = `先前黑K實體跌破${lines}，${isWeekly ? "本週" : "今日"}開盤已高於該線的開盤基準。`;
  const url = tradingViewUrl(signal, isWeekly ? "W" : "D");
  if ("serviceWorker" in navigator) {
    try {
      const registration = await navigator.serviceWorker.ready;
      await registration.showNotification(title, {
        body,
        icon: "assets/kj-radar-icon.svg",
        tag: `line-reclaim-${signal.signal_id}-${lines}`,
        data: { url },
      });
      return;
    } catch (error) {
      console.warn("PWA通知失敗，改用瀏覽器通知", error);
    }
  }
  const notification = new Notification(title, { body, icon: "assets/kj-radar-icon.svg", tag: `line-reclaim-${signal.signal_id}-${lines}` });
  notification.onclick = () => window.open(url, "_blank", "noopener,noreferrer");
}

function notifyOpeningReclaims(signals) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const notified = notifiedLineAlertKeys();
  for (const signal of signals) {
    // Keep latest-session cards visible after the close, but never replay an
    // old opening event as a fresh browser notification.
    if (!(signal.is_current_period_bar ?? signal.is_current_daily_bar)) continue;
    const lines = lineNames(signal, "opening_reclaim_lines").sort().join("+");
    const key = `${signal.signal_id || signal.tradingview_symbol}:${lines}`;
    if (!lines || notified.has(key)) continue;
    notified.add(key);
    showLineReclaimNotification(signal).catch((error) => console.warn("開盤站回通知失敗", error));
  }
  saveNotifiedLineAlertKeys(notified);
}

function updateLineAlertControls() {
  if (!elements.enableLineAlerts) return;
  if (!("Notification" in window)) {
    elements.enableLineAlerts.textContent = "此瀏覽器不支援通知";
    elements.enableLineAlerts.disabled = true;
    return;
  }
  const labels = {
    granted: "網站通知已開啟",
    denied: "網站通知已封鎖",
    default: "開啟網站通知",
  };
  elements.enableLineAlerts.textContent = labels[Notification.permission] || labels.default;
  elements.enableLineAlerts.disabled = Notification.permission === "denied";
}

async function enableLineAlerts() {
  if (!("Notification" in window)) return;
  const permission = await Notification.requestPermission();
  updateLineAlertControls();
  if (permission === "granted" && sequentialPayload) renderDailyLineReclaims(sequentialPayload);
}

function renderDailyLineReclaims(payload) {
  if (!elements.openingReclaimSignals || !elements.firstReclaimSignals) return;
  const frames = Array.isArray(payload?.timeframes) ? payload.timeframes : [];
  const dailyFrame = frames.find((frame) => frame.key === "1d") || {};
  const dailyMonitor = dailyFrame.daily_line_reclaims || {};
  const weeklyMonitor = payload?.weekly_reclaim?.line_reclaims || {};
  const monitor = lineReclaimFilterState.timeframe === "1w" ? weeklyMonitor : dailyMonitor;
  const signals = Array.isArray(monitor.signals) ? monitor.signals : [];
  // The left panel is an opening-time live feed, not a history list.  Once a
  // symbol's market closes (or before its next session opens), its old opening
  // event disappears.  Completed/latest first-body reclaims remain on the
  // right so off-hours review still has useful candidates.
  const liveOpeningSignals = signals.filter((signal) => (
    lineNames(signal, "opening_reclaim_lines").length > 0
    && (signal.is_current_period_bar ?? signal.is_current_daily_bar)
    && signal.is_live_session
  ));
  const latestFirstSignals = signals.filter((signal) => (
    lineNames(signal, "first_reclaim_lines").length > 0
    && signal.first_reclaim_confirmed === true
  ));
  const openingSignals = filteredLineReclaims(liveOpeningSignals, "opening_reclaim_lines");
  const firstSignals = filteredLineReclaims(latestFirstSignals, "first_reclaim_lines");
  renderLineReclaimList(elements.openingReclaimSignals, openingSignals, "opening");
  renderLineReclaimList(elements.firstReclaimSignals, firstSignals, "first");
  elements.openingReclaimCount.textContent = String(openingSignals.length);
  elements.firstReclaimCount.textContent = String(firstSignals.length);
  const weekly = lineReclaimFilterState.timeframe === "1w";
  elements.openingReclaimTitle.textContent = weekly ? "下一週開盤立即站回" : "隔日開盤立即站回";
  elements.firstReclaimTitle.textContent = `已確認${weekly ? "週線" : "日線"}站回第一根`;
  elements.lineReclaimUpdated.textContent = payload?.updated_at_utc
    ? `資料更新：${formatTaipei(payload.updated_at_utc)}`
    : `等待首次${weekly ? "週線" : "日線"}掃描`;
  const markets = Object.entries(monitor.scanned_by_market || {})
    .map(([market, count]) => `${displayMarket(market)} ${Number(count).toLocaleString("zh-TW")} 檔`)
    .join("、");
  elements.lineReclaimScanCount.textContent = monitor.scanned_symbols
    ? `本輪${weekly ? "週線" : "日線"}掃描 ${Number(monitor.scanned_symbols).toLocaleString("zh-TW")} 檔${markets ? `｜${markets}` : ""}`
    : `等待新版${weekly ? "週線" : "日線"}站回資料`;
  const allLiveOpeningSignals = [dailyMonitor, weeklyMonitor].flatMap((item) => (
    Array.isArray(item?.signals) ? item.signals : []
  )).filter((signal) => (
    lineNames(signal, "opening_reclaim_lines").length > 0
    && (signal.is_current_period_bar ?? signal.is_current_daily_bar)
    && signal.is_live_session
  ));
  notifyOpeningReclaims(allLiveOpeningSignals);
  updateLineAlertControls();
  updateLineReclaimFilterControls();
}

function selectedMarkets() {
  return new Set(
    elements.marketFilters
      .filter((control) => control.checked)
      .map((control) => control.value)
  );
}

function isSelectedMarket(signal, markets = selectedMarkets()) {
  return markets.has(displayMarket(signal?.market));
}

function makeTodayChange(value, label = "今日漲跌") {
  const percentage = Number(value);
  if (!Number.isFinite(percentage)) return null;
  const chip = document.createElement("span");
  chip.className = `today-change ${percentage > 0 ? "up" : percentage < 0 ? "down" : "flat"}`;
  chip.textContent = `${label}：${formatSigned(percentage)}%`;
  return chip;
}

function makeSparkline(values, direction, animate = false, options = {}) {
  const points = (Array.isArray(values) ? values : [])
    .map(Number)
    .filter((value) => Number.isFinite(value));
  if (points.length < 2) return null;

  const width = 176;
  const height = 42;
  const padding = 2;
  const minimum = Math.min(...points);
  const maximum = Math.max(...points);
  const range = maximum - minimum || 1;
  const coordinates = points.map((value, index) => {
    const x = (index / (points.length - 1)) * width;
    const y = height - padding - ((value - minimum) / range) * (height - padding * 2);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const namespace = "http://www.w3.org/2000/svg";
  const wrap = document.createElement("div");
  wrap.className = `future-sparkline ${direction}${animate ? " is-drawing" : ""}`;
  wrap.title = options.title || "當日 1 分鐘走勢";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-hidden", "true");
  const area = document.createElementNS(namespace, "polygon");
  area.setAttribute("class", "sparkline-area");
  area.setAttribute("points", `0,${height} ${coordinates.join(" ")} ${width},${height}`);
  const line = document.createElementNS(namespace, "polyline");
  line.setAttribute("class", "sparkline-line");
  line.setAttribute("points", coordinates.join(" "));
  const last = document.createElementNS(namespace, "circle");
  const [lastX, lastY] = coordinates.at(-1).split(",");
  last.setAttribute("class", "sparkline-last");
  last.setAttribute("cx", lastX);
  last.setAttribute("cy", lastY);
  last.setAttribute("r", "2.4");
  svg.append(area, line, last);
  const markerSpecs = Array.isArray(options.markers)
    ? options.markers
    : [{ index: options.markerIndex, kind: "signal" }];
  for (const markerSpec of markerSpecs) {
    const markerIndex = Number(markerSpec && markerSpec.index);
    if (!Number.isInteger(markerIndex) || markerIndex < 0 || markerIndex >= coordinates.length) continue;
    const [markerX, markerY] = coordinates[markerIndex].split(",");
    const marker = document.createElementNS(namespace, "circle");
    marker.setAttribute("class", `sparkline-${markerSpec && markerSpec.kind === "death" ? "death" : "signal"}`);
    marker.setAttribute("cx", markerX);
    marker.setAttribute("cy", markerY);
    marker.setAttribute("r", "3.2");
    svg.append(marker);
    const markerLabel = String(markerSpec?.label || "").trim();
    if (markerLabel) {
      const label = document.createElementNS(namespace, "text");
      label.setAttribute("class", `sparkline-marker-label ${markerSpec?.kind === "death" ? "death" : "signal"}`);
      label.setAttribute("x", markerX);
      label.setAttribute("y", String(Math.max(9, Number(markerY) - 7)));
      label.setAttribute("text-anchor", "middle");
      label.textContent = markerLabel;
      svg.append(label);
    }
  }
  wrap.append(svg);
  return wrap;
}

function makeFutureCard(future, index = 0, motion = {}) {
  const available = !future.unavailable && Number.isFinite(Number(future.last_price));
  const change = Number(future.change_pct || 0);
  const direction = change > 0 ? "up" : change < 0 ? "down" : "flat";
  const card = document.createElement("article");
  card.className = `future-card ${available ? direction : "unavailable"}${motion.enter ? " is-fresh" : ""}${motion.isNew ? " is-new" : ""}${motion.isUpdated ? " is-updated" : ""}`;
  card.style.setProperty("--card-delay", `${Math.min(index, 8) * 42}ms`);

  const labelRow = document.createElement("div");
  labelRow.className = "future-label-row";
  const label = document.createElement("p");
  label.className = "future-label";
  label.textContent = future.label || future.ticker;
  const pulse = document.createElement("span");
  pulse.className = `quote-pulse ${available ? `live ${direction}` : ""}`;
  pulse.setAttribute("aria-label", available ? "報價已載入" : "等待報價");
  labelRow.append(label, pulse);
  const price = document.createElement("strong");
  price.className = "future-price matrix-number";
  price.textContent = available ? formatMarketPrice(future.last_price, future.currency) : "—";
  if (available && (motion.isUpdated || motion.enter)) {
    const start = motion.isUpdated
      ? motion.previous.last_price
      : initialNumberStart(future.last_price, direction);
    animateNumber(
      price,
      start,
      future.last_price,
      (value) => formatMarketPrice(value, future.currency)
    );
  }
  const movement = document.createElement("p");
  movement.className = "future-movement matrix-number";
  movement.textContent = available
    ? `${formatSigned(future.change, future.currency === "TWD" ? 0 : 2)} · ${formatSigned(change)}%`
    : "報價暫時無法取得";
  if (available && (motion.isUpdated || motion.enter)) {
    const start = motion.isUpdated
      ? motion.previous.change
      : initialNumberStart(future.change, direction, true);
    animateNumber(movement, start, future.change, (value) => {
      const percentage = future.change ? (value / future.change) * change : change;
      return `${formatSigned(value, future.currency === "TWD" ? 0 : 2)} · ${formatSigned(percentage)}%`;
    });
  }
  const metadata = document.createElement("p");
  metadata.className = "future-meta";
  metadata.textContent = future.fallback_quote
    ? (future.quote_note || "期指指數替代報價")
    : future.as_of_utc
      ? `${Number(future.quote_interval_minutes || 1)} 分鐘 K · ${formatTaipei(future.as_of_utc)}`
      : "等待下一次更新";
  const sparkline = makeSparkline(future.sparkline, direction, motion.enter);
  card.append(labelRow, price, movement);
  if (sparkline) card.append(sparkline);
  card.append(metadata);

  if (future.tradingview_symbol) {
    const link = document.createElement("a");
    link.className = "future-link";
    link.href = marketTradingViewUrl(future.tradingview_symbol);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "T";
    link.title = "在 TradingView 開啟圖表";
    link.setAttribute("aria-label", "在 TradingView 開啟圖表");
    card.append(link);
  }
  return card;
}

function marketAgeText(value) {
  if (!value || Number.isNaN(new Date(value).getTime())) return "等待下一次更新";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `資料更新 · ${seconds} 秒前`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `資料更新 · ${minutes} 分鐘前`;
  return `資料更新 · ${formatTaipei(value)}`;
}

function refreshMarketAge() {
  elements.marketPulseUpdated.textContent = marketAgeText(marketUpdatedAt);
}

function makePremarketCard(mover, motion = {}) {
  const direction = mover.direction === "up" ? "up" : "down";
  const card = document.createElement("article");
  card.className = `premarket-card ${direction}${motion.enter ? " is-fresh" : ""}${motion.isNew ? " is-new" : ""}${motion.isUpdated ? " is-updated" : ""}`;
  const top = document.createElement("div");
  top.className = "alert-top";
  const name = document.createElement("div");
  const ticker = document.createElement("h3");
  ticker.className = "ticker";
  ticker.textContent = mover.symbol;
  const industry = document.createElement("p");
  industry.className = "exchange";
  industry.textContent = [mover.exchange, industryText(mover), mover.bar_time_et].filter(Boolean).join(" · ");
  name.append(ticker, industry);
  const change = document.createElement("strong");
  change.className = "premarket-change matrix-number";
  change.textContent = `${formatSigned(mover.change_pct)}%`;
  if (motion.isUpdated || motion.enter) {
    const start = motion.isUpdated
      ? motion.previous.change_pct
      : initialNumberStart(mover.change_pct, mover.direction, true);
    animateNumber(change, start, mover.change_pct, (value) => `${formatSigned(value)}%`);
  }
  top.append(name, change);

  const details = document.createElement("p");
  details.className = "premarket-details";
  const reference = mover.reference_label || "昨收";
  const latestLabel = document.createTextNode("最新 ");
  const latestPrice = document.createElement("strong");
  latestPrice.className = "premarket-price matrix-number";
  latestPrice.textContent = formatMarketPrice(mover.last_price, "USD");
  if (motion.isUpdated || motion.enter) {
    const start = motion.isUpdated
      ? motion.previous.last_price
      : initialNumberStart(mover.last_price, direction);
    animateNumber(latestPrice, start, mover.last_price, (value) => formatMarketPrice(value, "USD"));
  }
  details.append(latestLabel, latestPrice, document.createTextNode(`｜${reference} ${formatMarketPrice(mover.previous_close, "USD")}`));
  const sparkline = makeSparkline(mover.sparkline, direction, motion.enter);
  card.append(top, details);
  if (sparkline) card.append(sparkline);
  card.append(makeTradingViewLink(mover, "5"));
  return card;
}

function makeTaiwanTechnicalKpi(label, value, detail, tone = "") {
  const card = document.createElement("article");
  card.className = `taiex-tech-kpi ${tone}`.trim();
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value;
  const detailNode = document.createElement("small");
  detailNode.textContent = detail;
  card.append(labelNode, valueNode, detailNode);
  return card;
}

function technicalLinePath(bars, key, xFor, yFor) {
  let path = "";
  let connected = false;
  bars.forEach((bar, index) => {
    const value = Number(bar[key]);
    if (!Number.isFinite(value)) {
      connected = false;
      return;
    }
    path += `${connected ? "L" : "M"}${xFor(index).toFixed(2)} ${yFor(value).toFixed(2)} `;
    connected = true;
  });
  return path.trim();
}

function technicalRibbonPath(bars, xFor, yFor) {
  const upper = [];
  const lower = [];
  bars.forEach((bar, index) => {
    const high = Number(bar.ribbon_upper);
    const low = Number(bar.ribbon_lower);
    if (Number.isFinite(high) && Number.isFinite(low)) {
      upper.push(`${xFor(index).toFixed(2)},${yFor(high).toFixed(2)}`);
      lower.unshift(`${xFor(index).toFixed(2)},${yFor(low).toFixed(2)}`);
    }
  });
  return upper.length > 1 ? `${upper.join(" ")} ${lower.join(" ")}` : "";
}

function tdMarkerInfo(labels) {
  const values = Array.isArray(labels) ? labels.map(String) : [];
  const text = values.some((label) => label.includes("13")) ? "13" : values.some((label) => label.includes("9")) ? "9" : "";
  const buy = values.some((label) => /買方|buy/i.test(label));
  const sell = values.some((label) => /賣方|sell/i.test(label));
  return { text, side: buy ? "buy" : sell ? "sell" : "" };
}

function makeTaiwanTechnicalChart(payload) {
  const bars = Array.isArray(payload.bars) ? payload.bars.filter((bar) => Number.isFinite(Number(bar.close))) : [];
  if (bars.length < 2) return null;
  const namespace = "http://www.w3.org/2000/svg";
  const width = 1080;
  const height = 410;
  const plot = { left: 64, right: 22, top: 24, bottom: 48 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const values = bars.flatMap((bar) => [bar.low, bar.high, bar.white, bar.yellow, bar.ribbon_lower, bar.ribbon_upper])
    .map(Number)
    .filter(Number.isFinite);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const padding = Math.max((maximum - minimum) * 0.06, Math.max(Math.abs(maximum) * 0.002, 1));
  const scale = { min: minimum - padding, max: maximum + padding };
  const xFor = (index) => plot.left + (index / (bars.length - 1)) * plotWidth;
  const yFor = (value) => plot.top + ((scale.max - value) / (scale.max - scale.min || 1)) * plotHeight;
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("class", "taiex-tech-svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "台灣加權一小時 K 線、TD Sequential 與趨勢帶");

  for (let step = 0; step <= 4; step += 1) {
    const ratio = step / 4;
    const y = plot.top + plotHeight * ratio;
    const grid = document.createElementNS(namespace, "line");
    grid.setAttribute("class", "taiex-tech-grid");
    grid.setAttribute("x1", String(plot.left));
    grid.setAttribute("x2", String(width - plot.right));
    grid.setAttribute("y1", String(y));
    grid.setAttribute("y2", String(y));
    svg.append(grid);
    const label = document.createElementNS(namespace, "text");
    label.setAttribute("class", "taiex-tech-axis");
    label.setAttribute("x", String(plot.left - 9));
    label.setAttribute("y", String(y + 4));
    label.setAttribute("text-anchor", "end");
    label.textContent = new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 }).format(scale.max - (scale.max - scale.min) * ratio);
    svg.append(label);
  }

  const ribbon = technicalRibbonPath(bars, xFor, yFor);
  if (ribbon) {
    const polygon = document.createElementNS(namespace, "polygon");
    polygon.setAttribute("class", "taiex-tech-ribbon");
    polygon.setAttribute("points", ribbon);
    svg.append(polygon);
  }

  const candleWidth = Math.max(2.5, Math.min(8, (plotWidth / bars.length) * 0.62));
  bars.forEach((bar, index) => {
    const open = Number(bar.open);
    const high = Number(bar.high);
    const low = Number(bar.low);
    const close = Number(bar.close);
    if (![open, high, low, close].every(Number.isFinite)) return;
    const up = close >= open;
    const x = xFor(index);
    const wick = document.createElementNS(namespace, "line");
    wick.setAttribute("class", `taiex-tech-wick ${up ? "up" : "down"}`);
    wick.setAttribute("x1", String(x));
    wick.setAttribute("x2", String(x));
    wick.setAttribute("y1", String(yFor(high)));
    wick.setAttribute("y2", String(yFor(low)));
    const body = document.createElementNS(namespace, "rect");
    body.setAttribute("class", `taiex-tech-candle ${up ? "up" : "down"}`);
    body.setAttribute("x", String(x - candleWidth / 2));
    body.setAttribute("width", String(candleWidth));
    body.setAttribute("y", String(Math.min(yFor(open), yFor(close))));
    body.setAttribute("height", String(Math.max(1.3, Math.abs(yFor(open) - yFor(close)))));
    svg.append(wick, body);

    const marker = tdMarkerInfo(bar.td_labels);
    if (marker.text && marker.side) {
      const text = document.createElementNS(namespace, "text");
      const buy = marker.side === "buy";
      text.setAttribute("class", `taiex-td ${buy ? "buy" : "sell"}`);
      text.setAttribute("x", String(x));
      text.setAttribute("y", String(buy ? yFor(low) + 16 : yFor(high) - 8));
      text.setAttribute("text-anchor", "middle");
      text.textContent = marker.text;
      svg.append(text);
    }
  });

  for (const [key, className] of [["white", "white"], ["yellow", "yellow"]]) {
    const path = technicalLinePath(bars, key, xFor, yFor);
    if (!path) continue;
    const line = document.createElementNS(namespace, "path");
    line.setAttribute("class", `taiex-tech-line ${className}`);
    line.setAttribute("d", path);
    svg.append(line);
  }

  [0, Math.floor((bars.length - 1) / 2), bars.length - 1].forEach((index) => {
    const label = document.createElementNS(namespace, "text");
    label.setAttribute("class", "taiex-tech-axis");
    label.setAttribute("x", String(xFor(index)));
    label.setAttribute("y", String(height - 16));
    label.setAttribute("text-anchor", index === 0 ? "start" : index === bars.length - 1 ? "end" : "middle");
    label.textContent = formatTaipeiTimestamp(bars[index].time);
    svg.append(label);
  });

  const wrap = document.createElement("div");
  wrap.className = "taiex-tech-canvas";
  wrap.append(svg);
  const footer = document.createElement("div");
  footer.className = "taiex-tech-legend";
  footer.innerHTML = "<span><i class=\"white\"></i>白線</span><span><i class=\"yellow\"></i>黃線</span><span><i class=\"ribbon\"></i>EMA 50／100 趨勢帶</span><span><i class=\"td\"></i>TD 9／13</span>";
  const tv = document.createElement("a");
  tv.className = "future-link taiex-tech-tv";
  tv.href = `https://tw.tradingview.com/chart/?${new URLSearchParams({ symbol: payload.symbol || "TVC:TWII", interval: "60" }).toString()}`;
  tv.target = "_blank";
  tv.rel = "noopener noreferrer";
  tv.textContent = "T";
  tv.title = "以一小時框架在 TradingView 開啟台灣加權";
  tv.setAttribute("aria-label", tv.title);
  footer.append(tv);
  wrap.append(footer);
  return wrap;
}

function renderTaiwanTechnical(payload) {
  if (!elements.taiexTechnicalChart) return;
  const available = payload && payload.available && Array.isArray(payload.bars) && payload.bars.length > 1;
  elements.taiexTechnicalUpdated.textContent = available
    ? `最後完成 K 棒：${formatTaipeiTimestamp(payload.updated_at_utc)}`
    : "資料更新中";
  if (!available) {
    const empty = document.createElement("p");
    empty.className = "sentiment-empty";
    empty.textContent = (payload && payload.reason) || "等待台灣加權一小時資料同步。";
    elements.taiexTechnicalSummary.replaceChildren();
    elements.taiexTechnicalChart.replaceChildren(empty);
    return;
  }
  const trend = payload.trend || {};
  const recentEvent = Array.isArray(payload.recent_td_events) ? payload.recent_td_events.at(-1) : null;
  const labels = Array.isArray(recentEvent && recentEvent.labels) && recentEvent.labels.length
    ? recentEvent.labels.join("／")
    : "最近 84 根無 9／13";
  const tdDetail = recentEvent
    ? `${Number(recentEvent.age_bars || 0) === 0 ? "本根完成" : `${Number(recentEvent.age_bars)} 根前`}・${formatTaipeiTimestamp(recentEvent.time)}`
    : "Setup 9／Countdown 13";
  const reclaimAge = Number(trend.last_long_reclaim_bars_ago);
  const reclaimText = Number.isFinite(reclaimAge)
    ? (reclaimAge === 0 ? "本根完成 K 棒" : `${reclaimAge} 根 K 棒前`)
    : "近期尚未出現";
  const position = String(trend.ribbon_position || "趨勢帶資料待更新");
  const below = /下方/.test(position);
  elements.taiexTechnicalSummary.replaceChildren(
    makeTaiwanTechnicalKpi("台灣加權・1H", new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 }).format(Number(payload.latest_price)), "已排除未完成 K 棒", "price"),
    makeTaiwanTechnicalKpi("TD Sequential", labels, tdDetail, labels.includes("9") || labels.includes("13") ? "signal" : ""),
    makeTaiwanTechnicalKpi("趨勢帶／白黃線", position, String(trend.line_state || "線況待更新"), below ? "bearish" : ""),
    makeTaiwanTechnicalKpi("多方站回白線", reclaimText, "死亡交叉於趨勢帶下方後的站回條件", Number.isFinite(reclaimAge) && reclaimAge <= 5 ? "signal" : "")
  );
  elements.taiexTechnicalChart.replaceChildren(makeTaiwanTechnicalChart(payload));
}

function renderMarketPulse(payload) {
  const futures = Array.isArray(payload.futures) ? payload.futures : [];
  elements.futuresStrip.replaceChildren(
    ...futures.map((future, index) => {
      const previous = motionState.futures.get(future.key);
      const motion = { ...quoteMotion(previous, future, !motionState.hasMarket), previous };
      return makeFutureCard(future, index, motion);
    })
  );
  marketUpdatedAt = payload.updated_at_utc || null;
  refreshMarketAge();
  if (!marketAgeTimer) marketAgeTimer = window.setInterval(refreshMarketAge, 1_000);

  motionState.futures = quoteSnapshot(futures, "key");
  motionState.hasMarket = true;
}

function totalScannedSymbols(payload) {
  const frames = Array.isArray(payload?.timeframes) ? payload.timeframes : [];
  return frames.reduce((largest, frame) => Math.max(largest, Number(frame.scanned_symbols || 0)), 0);
}

function setScanProgress(percent, state, updatedAt = null) {
  if (!elements.scanProgress) return;
  const value = Math.max(0, Math.min(100, Math.round(Number(percent) || 0)));
  elements.scanProgress.dataset.phase = value >= 100 ? "complete" : "scanning";
  elements.scanProgressFill.style.width = `${value}%`;
  elements.scanProgressTrack.setAttribute("aria-valuenow", String(value));
  elements.scanProgressPercent.textContent = `${value}%`;
  elements.scanProgressState.textContent = state;
  elements.scanProgressUpdated.textContent = updatedAt
    ? `最後更新：${formatTaipei(updatedAt)}`
    : "最後更新：等待資料";
}

function animateScanProgress(payload) {
  const total = totalScannedSymbols(payload);
  let value = 4;
  setScanProgress(value, total ? `掃描 ${total.toLocaleString("zh-TW")} 檔監測標的` : "讀取監測資料");
  const timer = window.setInterval(() => {
    value = Math.min(92, value + Math.max(4, Math.ceil((92 - value) / 3)));
    setScanProgress(value, total ? `掃描 ${total.toLocaleString("zh-TW")} 檔監測標的` : "讀取監測資料");
    if (value >= 92) window.clearInterval(timer);
  }, 115);
  window.setTimeout(() => {
    window.clearInterval(timer);
    setScanProgress(100, total ? `掃描完成 · ${total.toLocaleString("zh-TW")} 檔已更新` : "掃描完成", payload?.updated_at_utc || null);
  }, 660);
}

function tdTrendPositionText(position) {
  return {
    above_ribbon: "TD 產生 K 棒：趨勢帶上方",
    inside_ribbon: "TD 產生 K 棒：趨勢帶內",
    below_ribbon: "TD 產生 K 棒：趨勢帶下方",
  }[position] || "TD／趨勢帶位置：待下次掃描";
}

function weeklyOpenText(signal) {
  const state = signal.weekly_open_vs_white;
  const label = {
    above_white: "本週開盤：高於白線",
    at_white: "本週開盤：貼近白線",
    below_white: "本週開盤：低於白線",
  }[state];
  if (!label) return "本週開盤／白線：待下次掃描";
  const weekOpen = Number(signal.week_open_price);
  const white = Number(signal.week_open_white);
  if (!Number.isFinite(weekOpen) || !Number.isFinite(white)) return label;
  return `${label}（${weekOpen.toFixed(2)} vs ${white.toFixed(2)}）`;
}

function makeSequentialSignal(signal, interval) {
  const card = document.createElement("article");
  card.className = `sequential-signal ${signal.side || "mixed"}`;
  const top = document.createElement("div");
  top.className = "alert-top";

  const heading = document.createElement("div");
  const ticker = document.createElement("h4");
  ticker.textContent = signal.name ? `${signal.symbol} ${signal.name}` : signal.symbol;
  const age = document.createElement("p");
  age.className = "signal-age";
  age.textContent = Number(signal.age_bars) === 0 ? "最新已完成 K 棒" : `${signal.age_bars} 根 K 棒前`;
  heading.append(ticker, age);

  const price = document.createElement("strong");
  price.className = "signal-price";
  price.textContent = formatSignalPrice(signal);
  const quote = document.createElement("div");
  quote.className = "signal-quote";
  quote.append(price);
  const todayChange = makeTodayChange(signal.today_change_pct);
  if (todayChange) quote.append(todayChange);
  top.append(heading, quote);

  const details = document.createElement("div");
  details.className = "signal-details";
  const industry = document.createElement("span");
  industry.textContent = industryText(signal);
  const occurred = document.createElement("span");
  occurred.textContent = `訊號產生：${signal.bar_time_et || "資料不足"}`;
  const trendPosition = document.createElement("span");
  trendPosition.className = `td-trend-position ${signal.td_trend_position || "unknown"}`;
  trendPosition.textContent = tdTrendPositionText(signal.td_trend_position);
  const weeklyOpen = document.createElement("span");
  weeklyOpen.className = `weekly-open ${signal.weekly_open_vs_white || "unknown"}`;
  weeklyOpen.textContent = weeklyOpenText(signal);
  details.append(industry, occurred, trendPosition, weeklyOpen);

  const labels = document.createElement("div");
  labels.className = "signal-labels";
  for (const label of Array.isArray(signal.labels) ? signal.labels : []) {
    const badge = document.createElement("span");
    badge.textContent = label;
    labels.append(badge);
  }
  const chartDirection = (() => {
    const values = (Array.isArray(signal.sparkline) ? signal.sparkline : [])
      .map(Number)
      .filter(Number.isFinite);
    if (values.length < 2) return signal.side === "sell" ? "down" : "up";
    return values.at(-1) > values[0] ? "up" : values.at(-1) < values[0] ? "down" : "flat";
  })();
  const sparkline = makeSparkline(signal.sparkline, chartDirection, true, {
    title: "最近 30 根已完成 K 棒走勢；標記為 TD 訊號位置",
    markers: [{
      index: signal.sparkline_signal_index,
      kind: "signal",
      label: `TD ${tdMarkerInfo(signal.labels).text || ""}`.trim(),
    }],
  });
  if (sparkline) sparkline.classList.add("signal-sparkline");
  const momentum = signal.momentum || {};
  if (momentum.available) {
    const confirmation = document.createElement("p");
    confirmation.className = `signal-confirmation ${momentum.bearish_confirmed ? "confirmed" : "pending"}`;
    const priorBars = Number(momentum.prior_window_bars || 0);
    const priorCount = Number(momentum.prior_bearish_count || 0);
    const yellowMatchBars = Number(momentum.yellow_match_bars_ago);
    const yellowZoneText = {
      below_ribbon: "黃線在趨勢帶下方",
      lower_edge: "黃線位於趨勢帶下緣",
    }[momentum.yellow_zone_position] || "黃線資料不足";
    const yellowText = Number.isFinite(yellowMatchBars)
      ? `${yellowZoneText}且斜率向下（${yellowMatchBars} K 前）`
      : `近 ${Number(momentum.yellow_lookback_bars || 30)} K 黃線未同時在趨勢帶下緣／下方且斜率向下`;
    confirmation.textContent = momentum.bearish_confirmed
      ? `空方動能確認：符合｜賣方 TD・前 ${priorBars} K 空方動能 ${priorCount} 次・${yellowText}`
      : `空方動能確認：未完整符合｜賣方 TD・前 ${priorBars} K 空方動能 ${priorCount} 次・${yellowText}`;
    card.append(top, details, labels);
    if (sparkline) card.append(sparkline);
    card.append(confirmation, makeTradingViewLink(signal, interval));
  } else {
    card.append(top, details, labels);
    if (sparkline) card.append(sparkline);
    card.append(makeTradingViewLink(signal, interval));
  }
  return card;
}

function filteredTrendReclaims(frame) {
  const markets = selectedMarkets();
  const multiplier = elements.sequentialSort.value === "oldest" ? 1 : -1;
  const signals = (Array.isArray(frame.trend_reclaim_signals) ? frame.trend_reclaim_signals : [])
    .filter((signal) => signal.side === "buy" && signal.signal_type === "long_reclaim");
  return signals
    .filter((signal) => isSelectedMarket(signal, markets))
    .sort((left, right) => {
      const leftTime = Date.parse(left.occurred_at_utc || 0);
      const rightTime = Date.parse(right.occurred_at_utc || 0);
      return multiplier * (leftTime - rightTime);
    });
}

function makeTrendReclaimSignal(signal, interval) {
  const card = document.createElement("article");
  card.className = "trend-reclaim-signal";
  const top = document.createElement("div");
  top.className = "alert-top";

  const heading = document.createElement("div");
  const ticker = document.createElement("h4");
  ticker.textContent = signal.name ? `${signal.symbol} ${signal.name}` : signal.symbol;
  const status = document.createElement("p");
  status.className = "reclaim-status";
  status.textContent = Number(signal.age_bars) === 0 ? "做多｜最新回站白線" : `做多｜${signal.age_bars} 根 K 棒前回站白線`;
  heading.append(ticker, status);

  const price = document.createElement("strong");
  price.className = "signal-price";
  price.textContent = formatSignalPrice(signal);
  const quote = document.createElement("div");
  quote.className = "signal-quote";
  quote.append(price);
  const todayChange = makeTodayChange(signal.today_change_pct);
  if (todayChange) quote.append(todayChange);
  top.append(heading, quote);

  const details = document.createElement("div");
  details.className = "signal-details";
  const industry = document.createElement("span");
  industry.textContent = industryText(signal);
  const occurred = document.createElement("span");
  occurred.textContent = `回站時間：${signal.bar_time_et || "資料不足"}`;
  details.append(industry, occurred);

  const rule = document.createElement("p");
  rule.className = "reclaim-rule";
  rule.textContent = `全程位於 TT 趨勢帶下方｜白／黃死亡交叉：${signal.death_cross_time || "資料不足"}｜${Number(signal.death_cross_bars_ago || 0)} 根 K 後收盤站回白線`;

  const values = (Array.isArray(signal.sparkline) ? signal.sparkline : [])
    .map(Number)
    .filter(Number.isFinite);
  const direction = values.length >= 2 && values.at(-1) < values[0] ? "down" : "up";
  const sparkline = makeSparkline(signal.sparkline, direction, true, {
    title: "最近 30 根已完成 K 棒走勢；橘點為死亡交叉，藍點為站回白線",
    markers: [
      { index: signal.sparkline_death_index, kind: "death" },
      { index: signal.sparkline_signal_index, kind: "signal" },
    ],
  });
  if (sparkline) sparkline.classList.add("signal-sparkline");
  card.append(top, details, rule);
  if (sparkline) card.append(sparkline);
  const legend = document.createElement("p");
  legend.className = "trend-sparkline-legend";
  const death = document.createElement("span");
  const deathDot = document.createElement("i");
  death.append(deathDot, document.createTextNode("橘點：死亡交叉"));
  const reclaim = document.createElement("span");
  const reclaimDot = document.createElement("i");
  reclaimDot.className = "reclaim-dot";
  reclaim.append(reclaimDot, document.createTextNode("藍點：站回白線確認"));
  legend.append(death, reclaim);
  card.append(legend);
  card.append(makeTradingViewLink(signal, interval));
  return card;
}

function makeTrendReclaimTimeframe(frame) {
  const panel = document.createElement("section");
  panel.className = "trend-reclaim-timeframe";
  const signals = filteredTrendReclaims(frame);
  const header = document.createElement("div");
  header.className = "timeframe-header";
  const title = document.createElement("h4");
  title.textContent = frame.label || frame.key;
  const count = document.createElement("span");
  count.textContent = `訊號後 ${Number(frame.recent_bars || 8)} 根：${signals.length} 個`;
  header.append(title, count);
  panel.append(header);
  if (signals.length === 0) {
    const empty = document.createElement("p");
    empty.className = "timeframe-empty";
    empty.textContent = "目前沒有符合死亡交叉後站回白線的訊號。";
    panel.append(empty);
    return panel;
  }
  const list = document.createElement("div");
  list.className = "sequential-signals";
  for (const signal of signals) list.append(makeTrendReclaimSignal(signal, frame.tradingview_interval));
  panel.append(list);
  return panel;
}

function renderTrendReclaims(frames) {
  const eligibleFrames = frames.filter((frame) => ["15m", "1h"].includes(frame.key));
  elements.trendReclaimFrames.replaceChildren(...eligibleFrames.map(makeTrendReclaimTimeframe));
}

function plainQuote(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "資料不足";
  return number.toLocaleString("en-US", {
    minimumFractionDigits: number < 10 ? 2 : 0,
    maximumFractionDigits: number < 10 ? 4 : 2,
  });
}

function filteredWeeklyReclaims(frame) {
  const markets = selectedMarkets();
  const selectedFilter = elements.weeklyReclaimFilter?.value || "score";
  const signals = Array.isArray(frame?.signals) ? frame.signals : [];
  return signals
    .filter((signal) => signal.side === "buy" && signal.signal_type === "weekly_white_reclaim")
    .filter((signal) => isSelectedMarket(signal, markets))
    .filter((signal) => {
      if (selectedFilter === "second-foot") {
        return Boolean(signal.second_foot_now);
      }
      if (selectedFilter === "third-foot") {
        return Boolean(signal.third_foot_now);
      }
      if (selectedFilter === "first-foot") {
        return Boolean(signal.first_foot_now);
      }
      if (selectedFilter === "white-above-yellow") {
        return Boolean(signal.weekly_ai_white_above_yellow);
      }
      if (selectedFilter === "previous-big-black-above-white") {
        return Boolean(signal.previous_week_big_black_above_white);
      }
      return true;
    })
    .sort((left, right) => {
      const scoreGap = Number(right.score || 0) - Number(left.score || 0);
      if (scoreGap) return scoreGap;
      return Date.parse(right.occurred_at_utc || 0) - Date.parse(left.occurred_at_utc || 0);
    });
}

function makeLegacyWeeklyReclaimSignal(signal, interval) {
  const card = document.createElement("article");
  const directFocus = Boolean(signal.direct_focus);
  card.className = `weekly-reclaim-signal${directFocus ? " is-direct-focus" : ""}`;

  const top = document.createElement("div");
  top.className = "alert-top";
  const heading = document.createElement("div");
  const ticker = document.createElement("h4");
  ticker.textContent = signal.name ? `${signal.symbol} ${signal.name}` : signal.symbol;
  const status = document.createElement("p");
  status.className = "weekly-reclaim-status";
  const age = Number(signal.age_weeks || 0);
  status.textContent = age === 0 ? "做多｜本週開盤站回白線（即時觀察）" : `做多｜首週站回後第 ${age} 週追蹤`;
  heading.append(ticker, status);

  const quote = document.createElement("div");
  quote.className = "signal-quote";
  const price = document.createElement("strong");
  price.className = "signal-price";
  price.textContent = formatSignalPrice(signal);
  const weekChange = makeTodayChange(signal.week_change_pct, "本週漲跌");
  quote.append(price);
  if (weekChange) quote.append(weekChange);
  if (directFocus) {
    const focusLight = document.createElement("span");
    focusLight.className = "direct-focus-light";
    focusLight.innerHTML = '<i aria-hidden="true"></i>直接關注';
    quote.append(focusLight);
  }
  top.append(heading, quote);

  const details = document.createElement("div");
  details.className = "signal-details weekly-reclaim-details";
  const industry = document.createElement("span");
  industry.textContent = industryText(signal);
  const recovery = document.createElement("span");
  recovery.textContent = `實體跌破後第 ${Number(signal.weeks_to_reclaim || 0)} 週開盤站回`;
  const score = document.createElement("span");
  score.className = "weekly-score";
  score.textContent = `結構分數 ${Number(signal.score || 0)}%`;
  details.append(industry, recovery, score);

  const timeline = document.createElement("p");
  timeline.className = "weekly-reclaim-timeline";
  const deathCrossText = signal.death_cross_below_ribbon
    ? `白黃死亡交叉（帶下）：${signal.death_cross_time || "資料不足"}`
    : "白黃死亡交叉（帶下）：未偵測（僅輔助，不影響入選）";
  timeline.textContent = `週K收盤實體跌破 AI 白線：${signal.break_time || "資料不足"}　→　首週開盤站回：${signal.reclaim_time || "資料不足"}　｜　${deathCrossText}`;

  const stateList = document.createElement("div");
  stateList.className = "weekly-reclaim-states";
  const baseState = document.createElement("span");
  baseState.textContent = age === 0
    ? "主規則成立｜本週開盤已在 AI Momentum 白線上方"
    : `首週開盤站回成立｜目前為第 ${age} 週延續追蹤`;
  stateList.append(baseState);
  if (signal.first_week_pullback_reclaim) {
    const firstWeek = document.createElement("span");
    firstWeek.className = age === 0 ? "strong-bonus" : "hourly-pending";
    firstWeek.textContent = age === 0
      ? "輔助加分｜首週開盤在白線上方→盤中跌破→收回 ＋20"
      : "輔助結構｜首週曾開高、回踩後收回";
    stateList.append(firstWeek);
  }
  if (signal.first_week_closed_above_white) {
    const firstClose = document.createElement("span");
    firstClose.className = "bonus";
    firstClose.textContent = "輔助確認｜首週收盤仍在白線上方 ＋12";
    stateList.append(firstClose);
  }
  if (signal.week_close_above_white) {
    const currentClose = document.createElement("span");
    currentClose.className = "bonus";
    currentClose.textContent = "目前週K收盤在白線上方";
    stateList.append(currentClose);
  } else {
    const currentClose = document.createElement("span");
    currentClose.className = "hourly-pending";
    currentClose.textContent = "目前週K收盤已回到白線下（保留觀察）";
    stateList.append(currentClose);
  }
  if (signal.death_cross_below_ribbon) {
    const deathCross = document.createElement("span");
    deathCross.className = "bonus";
    deathCross.textContent = "輔助加分｜白黃死亡交叉發生在趨勢帶下 ＋10";
    stateList.append(deathCross);
  }
  if (signal.second_week_near_white_open) {
    const secondWeek = document.createElement("span");
    secondWeek.className = "bonus";
    secondWeek.textContent = `第 2 根週K開盤在白線上方、距白線 ${Number(signal.week_open_distance_pct || 0).toFixed(2)}% ＋8`;
    stateList.append(secondWeek);
  }

  const weeklyAiStatus = document.createElement("p");
  weeklyAiStatus.className = "weekly-white-status weekly-ai-status";
  if (signal.weekly_ai_white_yellow_available) {
    const crossAge = Number(signal.weekly_ai_golden_cross_weeks_ago);
    const crossAgeText = crossAge === 0 ? "\u672c\u9031\u5b8c\u6210" : `${crossAge} \u9031\u524d\u5b8c\u6210`;
    if (signal.weekly_ai_golden_cross) {
      weeklyAiStatus.textContent = `\u9031K AI \u767d\u7dda\u91d1\u53c9\u9ec3\u7dda\uff1a${crossAgeText}\uff08\u53ea\u4fdd\u7559\u6700\u8fd1 4 \u9031\u8a0a\u865f\uff09`;
      const goldenCross = document.createElement("span");
      goldenCross.className = "strong-bonus";
      goldenCross.textContent = `\u9031K AI \u767d\u7dda\u91d1\u53c9\u9ec3\u7dda\uff1a${crossAgeText}`;
      stateList.append(goldenCross);
    } else if (signal.weekly_ai_white_above_yellow) {
      weeklyAiStatus.textContent = "\u9031K AI \u767d\u7dda\u5728\u9ec3\u7dda\u4e0a\u65b9\uff0c\u4f46\u6700\u8fd1 4 \u9031\u672a\u91d1\u53c9";
    } else {
      weeklyAiStatus.textContent = "\u9031K AI \u767d\u7dda\u4ecd\u5728\u9ec3\u7dda\u4e0b\u65b9";
    }
  } else {
    weeklyAiStatus.textContent = "\u9031K AI \u767d\u3001\u9ec3\u7dda\u8cc7\u6599\u4e0d\u8db3";
  }

  const whiteStatus = document.createElement("p");
  whiteStatus.className = "weekly-white-status";
  const firstOpenDistance = Number(signal.first_week_open_distance_pct);
  const currentOpenDistance = Number(signal.week_open_distance_pct);
  const currentCloseDistance = Number(signal.week_close_distance_pct);
  const signedPercent = (value) => Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${value.toFixed(2)}%` : "資料不足";
  const firstBehavior = signal.first_week_pullback_reclaim
    ? "開盤在上方→盤中跌破→收回"
    : signal.first_week_open_above_white ? "開盤站在白線上方（主規則）" : "開盤未站上白線";
  const hourlyDistance = Number(signal.hourly_white_distance_pct);
  const hourlyStatus = signal.hourly_status_available
    ? `1H：${signal.hourly_above_white ? "已站上" : "未站上"}白線（${signedPercent(hourlyDistance)}）`
    : "1H：資料暫缺";
  whiteStatus.textContent = `AI 白線狀況｜首週：${firstBehavior}（開盤 ${signedPercent(firstOpenDistance)}）｜本週：開盤 ${signedPercent(currentOpenDistance)}、收盤 ${signedPercent(currentCloseDistance)}｜${hourlyStatus}`;
  if (signal.hourly_status_available) {
    const hourly = document.createElement("span");
    hourly.className = signal.hourly_above_white ? "bonus" : "hourly-pending";
    hourly.textContent = signal.hourly_above_white
      ? "1 小時同步站上白線 ＋15"
      : "1 小時尚未站上白線";
    stateList.append(hourly);
    if (Number(signal.hourly_reclaim_count || 0) > 0) {
      const hourlyCount = document.createElement("span");
      const secondWithinFour = Boolean(signal.hourly_second_reclaim_within_four_bars);
      const firstWeekFocus = Boolean(signal.first_week_is_current && signal.first_week_pullback_reclaim);
      hourlyCount.className = secondWithinFour && firstWeekFocus ? "direct-focus-state" : "hourly-pending";
      hourlyCount.textContent = secondWithinFour && firstWeekFocus
        ? `1 小時第 ${Number(signal.hourly_reclaim_count)} 次站回（${Number(signal.hourly_second_reclaim_bars_ago)} 根K內）＋35`
        : secondWithinFour
          ? `1 小時第 ${Number(signal.hourly_reclaim_count)} 次站回（${Number(signal.hourly_second_reclaim_bars_ago)} 根K內）；非第一週，不加大分`
        : signal.hourly_second_reclaim
          ? `1 小時第 ${Number(signal.hourly_reclaim_count)} 次站回已超過 4 根K，不加分`
          : `1 小時已站回 ${Number(signal.hourly_reclaim_count)} 次`;
      stateList.append(hourlyCount);
    }
  } else {
    const hourlyUnavailable = document.createElement("span");
    hourlyUnavailable.className = "hourly-pending";
    hourlyUnavailable.textContent = "1 小時資料暫缺";
    stateList.append(hourlyUnavailable);
  }

  const values = (Array.isArray(signal.sparkline) ? signal.sparkline : [])
    .map(Number)
    .filter(Number.isFinite);
  const direction = values.length >= 2 && values.at(-1) < values[0] ? "down" : "up";
  const sparkline = makeSparkline(signal.sparkline, direction, true, {
    title: "週線近 26 週走勢；橘點為白線／黃線死亡交叉，藍點為收盤站回 AI 白線",
    markers: [
      { index: signal.sparkline_death_index, kind: "death", label: "白黃死叉" },
      { index: signal.sparkline_signal_index, kind: "signal", label: "收回白線" },
    ],
  });
  if (sparkline) sparkline.classList.add("signal-sparkline");

  const valuesText = document.createElement("p");
  valuesText.className = "weekly-reclaim-values";
  const hourlyValues = signal.hourly_status_available
    ? ` ｜ 1H C ${plainQuote(signal.hourly_close)} / 白線 ${plainQuote(signal.hourly_white_line)}`
    : "";
  valuesText.textContent = `本週 O ${plainQuote(signal.week_open)} ／ L ${plainQuote(signal.week_low)} ／ C ${plainQuote(signal.week_close)} ｜ AI 白線（開盤基準）${plainQuote(signal.white_at_open)} ／ 目前 ${plainQuote(signal.white_line)} ／ 黃線 ${plainQuote(signal.weekly_ai_yellow)}${hourlyValues}`;

  card.append(top, details, timeline, stateList, whiteStatus, weeklyAiStatus);
  if (sparkline) card.append(sparkline);
  card.append(valuesText, makeTradingViewLink(signal, interval));
  return card;
}

function makeWeeklyReclaimSignal(signal, interval) {
  const card = document.createElement("article");
  const directFocus = Boolean(signal.direct_focus);
  card.className = `weekly-reclaim-signal${directFocus ? " is-direct-focus" : ""}`;

  const top = document.createElement("div");
  top.className = "alert-top";
  const heading = document.createElement("div");
  const ticker = document.createElement("h4");
  ticker.textContent = signal.name ? `${signal.symbol} ${signal.name}` : signal.symbol;
  const status = document.createElement("p");
  status.className = "weekly-reclaim-status";
  status.textContent = `做多｜第 ${Number(signal.current_week_number || 0)} 根週K白線追蹤`;
  heading.append(ticker, status);

  const quote = document.createElement("div");
  quote.className = "signal-quote";
  const price = document.createElement("strong");
  price.className = "signal-price";
  price.textContent = formatSignalPrice(signal);
  quote.append(price);
  const weekChange = makeTodayChange(signal.week_change_pct, "本週漲跌");
  if (weekChange) quote.append(weekChange);
  if (directFocus) {
    const focusLight = document.createElement("span");
    focusLight.className = "direct-focus-light";
    focusLight.innerHTML = '<i aria-hidden="true"></i>直接關注';
    quote.append(focusLight);
  }
  top.append(heading, quote);

  const details = document.createElement("div");
  details.className = "signal-details weekly-reclaim-details";
  const industry = document.createElement("span");
  industry.textContent = industryText(signal);
  const recovery = document.createElement("span");
  recovery.textContent = `整根實體跌破後第 ${Number(signal.weeks_to_reclaim || 0)} 根收盤站回`;
  const score = document.createElement("span");
  score.className = "weekly-score";
  score.textContent = `結構分數 ${Number(signal.score || 0)}%`;
  details.append(industry, recovery, score);

  const timeline = document.createElement("p");
  timeline.className = "weekly-reclaim-timeline";
  timeline.textContent = `有效實體跌破白線：${signal.break_time || "資料不足"}　→　首根收盤站回：${signal.reclaim_time || "資料不足"}`;

  const stateList = document.createElement("div");
  stateList.className = "weekly-reclaim-states";
  const baseState = document.createElement("span");
  baseState.textContent = `主規則成立｜第 ${Number(signal.current_week_number || 0)} 根週K，開盤與收盤都在 AI 白線上`;
  stateList.append(baseState);

  const footLabel = signal.second_foot_now
    ? "最高優先｜第 2 根週K盤中跌破白線 0.1% 後剛收回"
    : signal.third_foot_now
      ? "次高優先｜第 3 根週K盤中跌破白線 0.1% 後剛收回"
      : signal.first_foot_now
        ? "第 1 根週K盤中跌破白線 0.1% 後剛收回"
        : null;
  if (footLabel) {
    const foot = document.createElement("span");
    foot.className = signal.second_foot_now ? "direct-focus-state" : "strong-bonus";
    foot.textContent = `${footLabel}（下探 ${Number(signal.foot_depth_pct || 0).toFixed(2)}%）`;
    stateList.append(foot);
  } else if (signal.had_first_foot) {
    const priorFoot = document.createElement("span");
    priorFoot.className = "bonus";
    priorFoot.textContent = "首根週K曾盤中跌破白線後收回";
    stateList.append(priorFoot);
  }

  const weeklyAiStatus = document.createElement("p");
  weeklyAiStatus.className = "weekly-white-status weekly-ai-status";
  if (signal.weekly_ai_white_yellow_available) {
    if (signal.weekly_ai_white_above_yellow) {
      weeklyAiStatus.textContent = "週K白線位於黃線上方（+10%）；不要求近期黃金交叉";
    } else {
      weeklyAiStatus.textContent = "週K白線仍在黃線下方；不給白黃趨勢加分";
    }
  } else {
    weeklyAiStatus.textContent = "週K白線／黃線資料不足";
  }

  const hourlyNumber = Number(signal.hourly_bar_number || 0);
  const hourlyDistance = Number(signal.hourly_white_distance_pct);
  const signedPercent = (value) => Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${value.toFixed(2)}%` : "資料不足";
  if (signal.previous_week_big_black_above_white) {
    const previousBlack = document.createElement("span");
    previousBlack.className = "strong-bonus";
    previousBlack.textContent = `前一根週K｜白線上大黑K（實體 ${signedPercent(signal.previous_week_body_change_pct)}）`;
    stateList.append(previousBlack);
  }
  const whiteStatus = document.createElement("p");
  whiteStatus.className = "weekly-white-status";
  whiteStatus.textContent = `週K白線狀況｜首根開盤 ${signedPercent(signal.first_week_open_distance_pct)}；本週開盤 ${signedPercent(signal.week_open_distance_pct)}、收盤 ${signedPercent(signal.week_close_distance_pct)}`;
  if (signal.hourly_status_available) {
    const hourly = document.createElement("span");
    hourly.className = signal.hourly_within_three ? "bonus" : "hourly-pending";
    hourly.textContent = hourlyNumber === 1
      ? "1H 加分｜剛站回白線第 1 根 ＋10%"
      : hourlyNumber === 2
        ? "1H 加分｜站回白線第 2 根 ＋7%"
        : hourlyNumber === 3
          ? "1H 加分｜站回白線第 3 根 ＋4%"
          : hourlyNumber > 3
            ? `1H 加分｜站上白線已第 ${hourlyNumber} 根，不加即時分`
            : "1H 加分｜尚未站上白線";
    stateList.append(hourly);
  }
  if (signal.monthly_white_available) {
    const monthly = document.createElement("span");
    monthly.className = signal.monthly_above_white ? "monthly-bonus" : "hourly-pending";
    const monthlyDistance = signedPercent(Number(signal.monthly_white_distance_pct));
    monthly.textContent = signal.monthly_above_white
      ? `月線加分｜收盤在 AI 白線上方 ${monthlyDistance} ＋10%`
      : `月線未站上 AI 白線（${monthlyDistance}）`;
    stateList.append(monthly);
  } else {
    const monthlyUnavailable = document.createElement("span");
    monthlyUnavailable.className = "hourly-pending";
    monthlyUnavailable.textContent = "月線白線資料暫缺";
    stateList.append(monthlyUnavailable);
  }

  const values = (Array.isArray(signal.sparkline) ? signal.sparkline : []).map(Number).filter(Number.isFinite);
  const direction = values.length >= 2 && values.at(-1) < values[0] ? "down" : "up";
  const sparkline = makeSparkline(signal.sparkline, direction, true, {
    title: "週線近 26 週走勢；藍點為首根收盤站回 AI 白線",
    markers: [{ index: signal.sparkline_signal_index, kind: "signal", label: "站回" }],
  });
  if (sparkline) sparkline.classList.add("signal-sparkline");

  const valuesText = document.createElement("p");
  valuesText.className = "weekly-reclaim-values";
  const hourlyValues = signal.hourly_status_available
    ? ` ｜ 1H C ${plainQuote(signal.hourly_close)} / 白線 ${plainQuote(signal.hourly_white_line)}`
    : "";
  const monthlyValues = signal.monthly_white_available
    ? ` ｜ 月 C ${plainQuote(signal.monthly_close)} / 白線 ${plainQuote(signal.monthly_white_line)}`
    : "";
  valuesText.textContent = `本週 O ${plainQuote(signal.week_open)} ／ L ${plainQuote(signal.week_low)} ／ C ${plainQuote(signal.week_close)} ｜ AI 白線（開盤基準）${plainQuote(signal.white_at_open)} ／ 目前 ${plainQuote(signal.white_line)} ／ 黃線 ${plainQuote(signal.weekly_ai_yellow)}${hourlyValues}${monthlyValues}`;

  card.append(top, details, timeline, stateList, whiteStatus, weeklyAiStatus);
  if (sparkline) card.append(sparkline);
  card.append(valuesText, makeTradingViewLink(signal, interval));
  return card;
}

function renderWeeklyReclaims(payload) {
  if (!elements.weeklyReclaimSignals) return;
  const frame = payload?.weekly_reclaim || {};
  const signals = filteredWeeklyReclaims(frame);
  if (signals.length === 0) {
    const empty = document.createElement("p");
    empty.className = "timeframe-empty";
    empty.textContent = `目前篩選市場中，沒有近 ${Number(frame.lookback_weeks || 3)} 週整根實體跌破白線後、收盤站回且仍在第 1～3 根追蹤內的結構。`;
    elements.weeklyReclaimSignals.replaceChildren(empty);
  } else {
    elements.weeklyReclaimSignals.replaceChildren(
      ...signals.map((signal) => makeWeeklyReclaimSignal(signal, frame.tradingview_interval || "W"))
    );
  }
  if (elements.weeklyReclaimExportNote) {
    elements.weeklyReclaimExportNote.textContent = signals.length
      ? `目前篩選市場可匯出 ${new Set(signals.map(tradingViewImportSymbol).filter(Boolean)).size} 個週線白線收復標的；清單按結構分數排序。`
      : "目前篩選市場沒有可匯出的週線白線收復標的。";
  }
}

function filteredSignals(frame) {
  const markets = selectedMarkets();
  const selectedSide = elements.sequentialSide.value;
  const selectedMomentum = elements.sequentialMomentum.value;
  const multiplier = elements.sequentialSort.value === "oldest" ? 1 : -1;
  const signals = Array.isArray(frame.signals) ? frame.signals : [];
  return signals
    .filter((signal) => isSelectedMarket(signal, markets))
    .filter((signal) => selectedSide === "all" || signal.side === selectedSide)
    .filter((signal) => selectedMomentum === "all" || Boolean(signal.momentum && signal.momentum.bearish_confirmed))
    .sort((left, right) => {
      const leftTime = Date.parse(left.occurred_at_utc || 0);
      const rightTime = Date.parse(right.occurred_at_utc || 0);
      return multiplier * (leftTime - rightTime);
    });
}

function tradingViewImportSymbol(signal) {
  if (signal.tradingview_symbol) return String(signal.tradingview_symbol).trim();
  const symbol = String(signal.symbol || "").trim().toUpperCase();
  const exchange = String(signal.exchange || "").trim().toUpperCase();
  if (!symbol || !exchange) return "";
  return `${exchange}:${symbol}`;
}

function exportSortKey(signal) {
  const marketOrder = { "台股": 0, "美股": 1, "幣安 USDT 永續": 2, "Pepperstone CFD": 3 };
  const product = String(signal.product_category || signal.industry || "其他");
  const industry = String(signal.industry || "");
  return [marketOrder[signal.market] ?? 99, product, industry, tradingViewImportSymbol(signal)];
}

function compareExportSignals(left, right) {
  const leftKey = exportSortKey(left);
  const rightKey = exportSortKey(right);
  for (let index = 0; index < leftKey.length; index += 1) {
    const comparison = String(leftKey[index]).localeCompare(String(rightKey[index]), "zh-Hant");
    if (comparison !== 0) return comparison;
  }
  return 0;
}

function selectedSignalsForExport() {
  const frames = Array.isArray(sequentialPayload?.timeframes) ? sequentialPayload.timeframes : [];
  const markets = selectedMarkets();
  const unique = new Map();
  for (const frame of frames) {
    const signals = Array.isArray(frame.signals) ? frame.signals : [];
    for (const signal of signals) {
      if (signal.side !== "buy") continue;
      if (!isSelectedMarket(signal, markets)) continue;
      const symbol = tradingViewImportSymbol(signal);
      if (!symbol) continue;
      const previous = unique.get(symbol);
      const signalTime = Date.parse(signal.occurred_at_utc || 0);
      const previousTime = Date.parse(previous?.occurred_at_utc || 0);
      if (!previous || signalTime > previousTime) unique.set(symbol, signal);
    }
  }
  return [...unique.values()]
    .sort(compareExportSignals)
    .map((signal) => tradingViewImportSymbol(signal));
}

function selectedWeeklyReclaimsForExport() {
  const signals = filteredWeeklyReclaims(sequentialPayload?.weekly_reclaim || {});
  const unique = new Map();
  for (const signal of signals) {
    const symbol = tradingViewImportSymbol(signal);
    if (!symbol || unique.has(symbol)) continue;
    unique.set(symbol, signal);
  }
  return [...unique.values()]
    .sort((left, right) => Number(right.score || 0) - Number(left.score || 0) || compareExportSignals(left, right))
    .map(tradingViewImportSymbol);
}

function downloadTradingViewList() {
  const symbols = selectedSignalsForExport();
  if (symbols.length === 0) {
    elements.tradingViewExportNote.textContent = "目前市場沒有可匯出的做多 TD 標的。";
    return;
  }
  const content = `${symbols.join("\n")}\n`;
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = `KJ-Radar-TD-long-${new Date().toISOString().slice(0, 10)}.txt`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
  elements.tradingViewExportNote.textContent = `已產生 ${symbols.length} 個不重複做多代號；已依市場、主力產品／產業與代號排序，可直接在 TradingView 匯入。`;
}

function downloadWeeklyTradingViewList() {
  const symbols = selectedWeeklyReclaimsForExport();
  if (symbols.length === 0) {
    if (elements.weeklyReclaimExportNote) {
      elements.weeklyReclaimExportNote.textContent = "目前篩選市場沒有可匯出的週線白線收復標的。";
    }
    return;
  }
  const blob = new Blob([`${symbols.join("\n")}\n`], { type: "text/plain;charset=utf-8" });
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = `KJ-Radar-Weekly-White-Reclaim-${new Date().toISOString().slice(0, 10)}.txt`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
  if (elements.weeklyReclaimExportNote) {
    elements.weeklyReclaimExportNote.textContent = `已產生 ${symbols.length} 個週線白線收復標的；可直接匯入 TradingView 觀察清單。`;
  }
}

function makeTimeframe(frame) {
  const panel = document.createElement("section");
  panel.className = "timeframe";
  const header = document.createElement("div");
  header.className = "timeframe-header";
  const title = document.createElement("h3");
  title.textContent = frame.label || frame.key;
  const count = document.createElement("span");
  const signals = filteredSignals(frame);
  const recentBars = Number(frame.recent_bars || 8);
  count.textContent = `訊號後 ${recentBars} 根：${signals.length} 個`;
  header.append(title, count);
  panel.append(header);

  const meta = document.createElement("p");
  meta.className = "timeframe-meta";
  const markets = Object.entries(frame.scanned_by_market || {})
    .map(([market, count]) => `${market} ${count} 檔`)
    .join("、");
  meta.textContent = `已計算 ${String(frame.scanned_symbols || 0)} 檔${markets ? `（${markets}）` : ""} · ${frame.last_completed_bar_et || "尚無資料"}`;
  panel.append(meta);

  if (signals.length === 0) {
    const empty = document.createElement("p");
    empty.className = "timeframe-empty";
    empty.textContent = `目前篩選範圍中，訊號後 ${recentBars} 根已完成 K 棒內沒有 Setup 9 或 Countdown 13。`;
    panel.append(empty);
    return panel;
  }

  const signalList = document.createElement("div");
  signalList.className = "sequential-signals";
  for (const signal of signals) {
    signalList.append(makeSequentialSignal(signal, frame.tradingview_interval));
  }
  panel.append(signalList);
  return panel;
}

function renderSequential(payload) {
  sequentialPayload = payload;
  const frames = Array.isArray(payload.timeframes) ? payload.timeframes : [];
  renderDailyLineReclaims(payload);
  elements.sequentialFrames.replaceChildren(...frames.map(makeTimeframe));
  renderTrendReclaims(frames);
  renderWeeklyReclaims(payload);
  elements.sequentialUpdated.textContent = payload.updated_at_utc
    ? `資料更新：${formatTaipei(payload.updated_at_utc)}`
    : "等待首次資料更新";
  elements.sequentialSource.textContent = payload.source || "";
  const exportCount = selectedSignalsForExport().length;
  elements.tradingViewExportNote.textContent = exportCount
    ? `目前市場可匯出 ${exportCount} 個不重複做多代號；已依市場、主力產品／產業與代號排序。`
    : "目前市場沒有可匯出的做多 TD 標的。";
  animateScanProgress(payload);
}

async function loadJson(path) {
  const response = await fetch(`${path}?cache=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`無法讀取 ${path}`);
  return response.json();
}

async function loadLatestWorkflowRun() {
  const response = await fetch(ACTIONS_RUNS_URL, {
    cache: "no-store",
    headers: { Accept: "application/vnd.github+json" },
  });
  if (!response.ok) throw new Error(`無法讀取 GitHub Actions 狀態（${response.status}）`);
  const payload = await response.json();
  return Array.isArray(payload.workflow_runs) ? payload.workflow_runs[0] || null : null;
}

async function loadCurrentWorkflowStatus() {
  if (Date.now() - latestWorkflowResult.checkedAt < ACTIONS_POLL_INTERVAL_MS) {
    return latestWorkflowResult;
  }
  try {
    latestWorkflowResult = { run: await loadLatestWorkflowRun(), error: null, checkedAt: Date.now() };
  } catch (error) {
    latestWorkflowResult = { run: null, error, checkedAt: Date.now() };
  }
  return latestWorkflowResult;
}

async function refresh() {
  elements.refresh.disabled = true;
  elements.refresh.textContent = "更新中…";
  try {
    const [sequential, market, workflowResult] = await Promise.all([
      loadJson("data/sequential.json"),
      loadJson("data/market.json"),
      loadCurrentWorkflowStatus(),
    ]);
    renderSequential(sequential);
    renderMarketPulse(market);
    renderSystemStatus(sequential, workflowResult.run, workflowResult.error);
  } catch (error) {
    elements.sequentialSource.textContent = "資料讀取失敗；請稍後重試，或查看 GitHub Actions 的最近執行結果。";
    renderSystemStatus(null, null, error);
    console.error(error);
  } finally {
    elements.refresh.disabled = false;
    elements.refresh.textContent = "更新畫面";
  }
}

function setInstallNote(message) {
  if (!elements.installAppNote) return;
  elements.installAppNote.textContent = message;
  elements.installAppNote.hidden = !message;
}

function isAppleMobile() {
  return /iPhone|iPad|iPod/i.test(navigator.userAgent);
}

function isStandaloneApp() {
  return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
}

function configureAppInstall() {
  if (!elements.installApp) return;
  if (isStandaloneApp()) {
    elements.installApp.hidden = true;
    setInstallNote("目前正以已安裝的 KJ Radar App 執行。");
    return;
  }
  if (isAppleMobile()) {
    elements.installApp.hidden = false;
    elements.installApp.textContent = "加入主畫面";
  }
}

async function installApp() {
  if (!elements.installApp) return;
  if (deferredInstallPrompt) {
    deferredInstallPrompt.prompt();
    const choice = await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    elements.installApp.hidden = true;
    setInstallNote(choice.outcome === "accepted" ? "KJ Radar 正在安裝。" : "你可以稍後再按安裝 App。" );
    return;
  }
  if (isAppleMobile()) {
    setInstallNote("請按 Safari 的「分享」按鈕，選擇「加入主畫面」，即可安裝 KJ Radar。" );
    return;
  }
  setInstallNote("請使用 Chrome 或 Edge 的瀏覽器選單，選擇「安裝 KJ Radar System」；符合安裝條件時按鈕會自動出現。" );
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js", { scope: "./" }).catch((error) => {
      console.warn("KJ Radar App 離線功能初始化失敗", error);
    });
  });
}

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  if (elements.installApp && !isStandaloneApp()) {
    elements.installApp.hidden = false;
    elements.installApp.textContent = "安裝 App";
  }
});
window.addEventListener("appinstalled", () => {
  deferredInstallPrompt = null;
  if (elements.installApp) elements.installApp.hidden = true;
  setInstallNote("KJ Radar App 已安裝，可從裝置主畫面開啟。" );
});

elements.refresh.addEventListener("click", refresh);
if (elements.enableLineAlerts) elements.enableLineAlerts.addEventListener("click", enableLineAlerts);
if (elements.installApp) elements.installApp.addEventListener("click", installApp);
for (const marketFilter of elements.marketFilters) {
  marketFilter.addEventListener("change", () => {
    if (sequentialPayload) renderSequential(sequentialPayload);
  });
}
elements.sequentialSort.addEventListener("change", () => {
  if (sequentialPayload) renderSequential(sequentialPayload);
});
elements.sequentialSide.addEventListener("change", () => {
  if (sequentialPayload) renderSequential(sequentialPayload);
});
elements.sequentialMomentum.addEventListener("change", () => {
  if (sequentialPayload) renderSequential(sequentialPayload);
});
if (elements.weeklyReclaimFilter) {
  elements.weeklyReclaimFilter.addEventListener("change", () => {
    if (sequentialPayload) renderWeeklyReclaims(sequentialPayload);
  });
}
for (const button of elements.lineReclaimTimeframeFilters) {
  button.addEventListener("click", () => {
    lineReclaimFilterState.timeframe = button.dataset.reclaimTimeframe || "1d";
    if (sequentialPayload) renderDailyLineReclaims(sequentialPayload);
  });
}
for (const button of elements.lineReclaimLineFilters) {
  button.addEventListener("click", () => {
    lineReclaimFilterState.line = button.dataset.reclaimLine || "all";
    if (sequentialPayload) renderDailyLineReclaims(sequentialPayload);
  });
}
for (const button of elements.lineReclaimMarketFilters) {
  button.addEventListener("click", () => {
    lineReclaimFilterState.market = button.dataset.reclaimMarket || "all";
    if (sequentialPayload) renderDailyLineReclaims(sequentialPayload);
  });
}
elements.downloadTradingViewList.addEventListener("click", downloadTradingViewList);
if (elements.downloadWeeklyTradingViewList) {
  elements.downloadWeeklyTradingViewList.addEventListener("click", downloadWeeklyTradingViewList);
}
configureAppInstall();
updateLineAlertControls();
refresh();
// The daily opening-reclaim panel is time-sensitive.  Data itself is fetched
// network-first, so this reflects a freshly deployed opening signal within
// seconds rather than waiting a full minute for the next page refresh.
setInterval(refresh, 15_000);
