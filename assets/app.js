const elements = {
  status: document.querySelector("#market-status"),
  count: document.querySelector("#alert-count"),
  updated: document.querySelector("#updated-at"),
  coverage: document.querySelector("#scan-coverage"),
  alerts: document.querySelector("#alerts"),
  empty: document.querySelector("#empty"),
  source: document.querySelector("#source-note"),
  refresh: document.querySelector("#refresh"),
  sequentialFrames: document.querySelector("#sequential-frames"),
  sequentialUpdated: document.querySelector("#sequential-updated"),
  sequentialSource: document.querySelector("#sequential-source"),
  sequentialMarket: document.querySelector("#sequential-market"),
  sequentialSort: document.querySelector("#sequential-sort"),
  sequentialSide: document.querySelector("#sequential-side"),
  sequentialMomentum: document.querySelector("#sequential-momentum"),
  marketPulseUpdated: document.querySelector("#market-pulse-updated"),
  futuresStrip: document.querySelector("#futures-strip"),
  premarketSummary: document.querySelector("#premarket-summary"),
  premarketMovers: document.querySelector("#premarket-movers"),
  premarketEmpty: document.querySelector("#premarket-empty"),
};

let sequentialPayload = null;
let marketUpdatedAt = null;
let marketAgeTimer = null;

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

function formatSigned(value, digits = 2) {
  const number = Number(value);
  const sign = number > 0 ? "+" : "";
  return `${sign}${number.toFixed(digits)}`;
}

function formatTaipei(value) {
  return new Intl.DateTimeFormat("zh-TW", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Asia/Taipei",
  }).format(new Date(value));
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
  return `https://www.tradingview.com/chart/?${query.toString()}`;
}

function marketTradingViewUrl(symbol) {
  const query = new URLSearchParams({ symbol: String(symbol || "") });
  query.set("interval", "5");
  return `https://www.tradingview.com/chart/?${query.toString()}`;
}

function makeTradingViewLink(item, interval, label = "在 TradingView 開啟圖表") {
  const link = document.createElement("a");
  link.className = "tv-link";
  link.href = tradingViewUrl(item, interval);
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = label;
  return link;
}

function makeAlertCard(alert) {
  const card = document.createElement("article");
  card.className = "alert-card";

  const top = document.createElement("div");
  top.className = "alert-top";
  const name = document.createElement("div");
  const ticker = document.createElement("h3");
  ticker.className = "ticker";
  ticker.textContent = alert.symbol;
  const exchange = document.createElement("p");
  exchange.className = "exchange";
  exchange.textContent = [alert.exchange, alert.industry, alert.bar_time_et].filter(Boolean).join(" · ");
  name.append(ticker, exchange);
  const drop = document.createElement("div");
  drop.className = "drop";
  drop.textContent = `${Number(alert.price_change_pct).toFixed(2)}%`;
  top.append(name, drop);

  const stats = document.createElement("div");
  stats.className = "stats";
  stats.append(
    makeStat("最新價格", formatCurrency(alert.last_price)),
    makeStat("5 分鐘量比", `${Number(alert.volume_multiple).toFixed(2)} 倍`),
    makeStat("近 4 日平均日成交額", formatCompactCurrency(alert.average_daily_dollar_volume))
  );
  card.append(top, stats, makeTradingViewLink(alert, "5"));
  return card;
}

function renderSelloff(payload) {
  const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
  const open = payload.market_status === "open";
  elements.status.textContent = open ? "美股一般盤中" : "美股一般盤外";
  elements.status.style.color = open ? "var(--accent)" : "var(--muted)";
  elements.count.textContent = String(alerts.length);
  elements.updated.textContent = payload.updated_at_utc ? formatTaipei(payload.updated_at_utc) : "—";
  elements.coverage.textContent = `已掃描 ${String(payload.scanned_symbols || 0)} 檔`;
  elements.source.textContent = payload.source || "";
  elements.alerts.replaceChildren(...alerts.map(makeAlertCard));
  elements.empty.hidden = alerts.length !== 0;
}

function makeSparkline(values, direction) {
  const points = (Array.isArray(values) ? values : [])
    .map(Number)
    .filter((value) => Number.isFinite(value));
  if (points.length < 2) return null;

  const width = 128;
  const height = 34;
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
  wrap.className = `future-sparkline ${direction}`;
  wrap.title = "當日 1 分鐘走勢";
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
  wrap.append(svg);
  return wrap;
}

function makeFutureCard(future, index = 0) {
  const available = !future.unavailable && Number.isFinite(Number(future.last_price));
  const change = Number(future.change_pct || 0);
  const direction = change > 0 ? "up" : change < 0 ? "down" : "flat";
  const card = document.createElement("article");
  card.className = `future-card ${available ? direction : "unavailable"} is-fresh`;
  card.style.setProperty("--card-delay", `${Math.min(index, 8) * 42}ms`);

  const labelRow = document.createElement("div");
  labelRow.className = "future-label-row";
  const label = document.createElement("p");
  label.className = "future-label";
  label.textContent = future.label || future.ticker;
  const pulse = document.createElement("span");
  pulse.className = `quote-pulse ${available ? "live" : ""}`;
  pulse.setAttribute("aria-label", available ? "報價已載入" : "等待報價");
  labelRow.append(label, pulse);
  const price = document.createElement("strong");
  price.className = "future-price";
  price.textContent = available ? formatMarketPrice(future.last_price, future.currency) : "—";
  const movement = document.createElement("p");
  movement.className = "future-movement";
  movement.textContent = available
    ? `${formatSigned(future.change, future.currency === "TWD" ? 0 : 2)} · ${formatSigned(change)}%`
    : "報價暫時無法取得";
  const metadata = document.createElement("p");
  metadata.className = "future-meta";
  metadata.textContent = future.fallback_quote
    ? (future.quote_note || "期指指數替代報價")
    : future.as_of_utc
      ? `${Number(future.quote_interval_minutes || 1)} 分鐘 K · ${formatTaipei(future.as_of_utc)}`
      : "等待下一次更新";
  const sparkline = makeSparkline(future.sparkline, direction);
  card.append(labelRow, price, movement);
  if (sparkline) card.append(sparkline);
  card.append(metadata);

  if (future.tradingview_symbol) {
    const link = document.createElement("a");
    link.className = "future-link";
    link.href = marketTradingViewUrl(future.tradingview_symbol);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "查看圖表";
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

function makePremarketCard(mover) {
  const card = document.createElement("article");
  card.className = `premarket-card ${mover.direction === "up" ? "up" : "down"}`;
  const top = document.createElement("div");
  top.className = "alert-top";
  const name = document.createElement("div");
  const ticker = document.createElement("h3");
  ticker.className = "ticker";
  ticker.textContent = mover.symbol;
  const industry = document.createElement("p");
  industry.className = "exchange";
  industry.textContent = [mover.exchange, mover.industry, mover.bar_time_et].filter(Boolean).join(" · ");
  name.append(ticker, industry);
  const change = document.createElement("strong");
  change.className = "premarket-change";
  change.textContent = `${formatSigned(mover.change_pct)}%`;
  top.append(name, change);

  const details = document.createElement("p");
  details.className = "premarket-details";
  const reference = mover.reference_label || "昨收";
  details.textContent = `最新 ${formatMarketPrice(mover.last_price, "USD")}｜${reference} ${formatMarketPrice(mover.previous_close, "USD")}`;
  card.append(top, details, makeTradingViewLink(mover, "5", "在 TradingView 檢視"));
  return card;
}

function renderMarketPulse(payload) {
  const futures = Array.isArray(payload.futures) ? payload.futures : [];
  elements.futuresStrip.replaceChildren(...futures.map(makeFutureCard));
  marketUpdatedAt = payload.updated_at_utc || null;
  refreshMarketAge();
  if (!marketAgeTimer) marketAgeTimer = window.setInterval(refreshMarketAge, 1_000);

  const premarket = payload.premarket || {};
  const movers = Array.isArray(premarket.movers) ? premarket.movers : [];
  const threshold = Number(premarket.threshold_pct || 2);
  elements.premarketSummary.textContent = premarket.active
    ? `美東盤前中 · 已掃描 ${Number(premarket.scanned_symbols || 0)} 檔 · 異常門檻 ±${threshold}%`
    : "僅於美東 04:00–09:30 掃描";
  if (premarket.binance_amd_enabled) {
    elements.premarketSummary.textContent += "｜AMDUSDT 夜盤合約持續監控";
  }
  elements.premarketMovers.replaceChildren(...movers.map(makePremarketCard));
  elements.premarketEmpty.hidden = movers.length !== 0;
  if (movers.length === 0) {
    elements.premarketEmpty.textContent = premarket.active
      ? `目前沒有指標股達到 ±${threshold}% 的盤前異常門檻。`
      : "目前非美股盤前時段；下一個盤前時段會自動更新。";
  }
}

function makeSequentialSignal(signal, interval) {
  const card = document.createElement("article");
  card.className = `sequential-signal ${signal.side || "mixed"}`;
  const top = document.createElement("div");
  top.className = "alert-top";

  const heading = document.createElement("div");
  const ticker = document.createElement("h4");
  ticker.textContent = signal.name ? `${signal.symbol} ${signal.name}` : signal.symbol;
  const time = document.createElement("p");
  time.className = "exchange";
  time.textContent = [signal.market || "市場", signal.exchange, signal.industry, signal.bar_time_et]
    .filter(Boolean)
    .join(" · ");
  const age = document.createElement("p");
  age.className = "signal-age";
  age.textContent = Number(signal.age_bars) === 0 ? "最新已完成 K 棒" : `${signal.age_bars} 根 K 棒前`;
  heading.append(ticker, time, age);

  const price = document.createElement("strong");
  price.className = "signal-price";
  price.textContent = formatCurrency(signal.last_price);
  top.append(heading, price);

  const labels = document.createElement("div");
  labels.className = "signal-labels";
  for (const label of Array.isArray(signal.labels) ? signal.labels : []) {
    const badge = document.createElement("span");
    badge.textContent = label;
    labels.append(badge);
  }
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
    card.append(top, labels, confirmation, makeTradingViewLink(signal, interval, "在 TradingView 檢視"));
  } else {
    card.append(top, labels, makeTradingViewLink(signal, interval, "在 TradingView 檢視"));
  }
  return card;
}

function filteredSignals(frame) {
  const selectedMarket = elements.sequentialMarket.value;
  const selectedSide = elements.sequentialSide.value;
  const selectedMomentum = elements.sequentialMomentum.value;
  const multiplier = elements.sequentialSort.value === "oldest" ? 1 : -1;
  const signals = Array.isArray(frame.signals) ? frame.signals : [];
  return signals
    .filter((signal) => selectedMarket === "all" || signal.market === selectedMarket)
    .filter((signal) => selectedSide === "all" || signal.side === selectedSide)
    .filter((signal) => selectedMomentum === "all" || Boolean(signal.momentum && signal.momentum.bearish_confirmed))
    .sort((left, right) => {
      const leftTime = Date.parse(left.occurred_at_utc || 0);
      const rightTime = Date.parse(right.occurred_at_utc || 0);
      return multiplier * (leftTime - rightTime);
    });
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
  const recentBars = Number(frame.recent_bars || 5);
  count.textContent = `最近 ${recentBars} 根：${signals.length} 個`;
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
    empty.textContent = `目前篩選範圍的最近 ${recentBars} 根已完成 K 棒，沒有 Setup 9 或 Countdown 13。`;
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
  elements.sequentialFrames.replaceChildren(...frames.map(makeTimeframe));
  elements.sequentialUpdated.textContent = payload.updated_at_utc
    ? `資料更新：${formatTaipei(payload.updated_at_utc)}`
    : "等待首次資料更新";
  elements.sequentialSource.textContent = payload.source || "";
}

async function loadJson(path) {
  const response = await fetch(`${path}?cache=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`無法讀取 ${path}`);
  return response.json();
}

async function refresh() {
  elements.refresh.disabled = true;
  elements.refresh.textContent = "更新中…";
  try {
    const [alerts, sequential, market] = await Promise.all([
      loadJson("data/alerts.json"),
      loadJson("data/sequential.json"),
      loadJson("data/market.json"),
    ]);
    renderSelloff(alerts);
    renderSequential(sequential);
    renderMarketPulse(market);
  } catch (error) {
    elements.status.textContent = "資料讀取失敗";
    elements.source.textContent = "請稍後重試；若持續發生，請查看 GitHub Actions 的最近執行結果。";
    console.error(error);
  } finally {
    elements.refresh.disabled = false;
    elements.refresh.textContent = "更新畫面";
  }
}

elements.refresh.addEventListener("click", refresh);
elements.sequentialMarket.addEventListener("change", () => {
  if (sequentialPayload) renderSequential(sequentialPayload);
});
elements.sequentialSort.addEventListener("change", () => {
  if (sequentialPayload) renderSequential(sequentialPayload);
});
elements.sequentialSide.addEventListener("change", () => {
  if (sequentialPayload) renderSequential(sequentialPayload);
});
elements.sequentialMomentum.addEventListener("change", () => {
  if (sequentialPayload) renderSequential(sequentialPayload);
});
refresh();
setInterval(refresh, 60_000);
