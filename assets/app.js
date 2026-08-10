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
  trendReclaimFrames: document.querySelector("#trend-reclaim-frames"),
  marketPulseUpdated: document.querySelector("#market-pulse-updated"),
  futuresStrip: document.querySelector("#futures-strip"),
  chipRadarUpdated: document.querySelector("#chip-radar-updated"),
  chipRadarSummary: document.querySelector("#chip-radar-summary"),
  chipRadarBacktest: document.querySelector("#chip-radar-backtest"),
  chipRadarCandidates: document.querySelector("#chip-radar-candidates"),
  chipRadarSource: document.querySelector("#chip-radar-source"),
  taiwanSentimentUpdated: document.querySelector("#taiwan-sentiment-updated"),
  taiwanSentimentKpis: document.querySelector("#taiwan-sentiment-kpis"),
  taiwanSentimentChart: document.querySelector("#taiwan-sentiment-chart"),
  taiwanSentimentSource: document.querySelector("#taiwan-sentiment-source"),
  premarketSummary: document.querySelector("#premarket-summary"),
  premarketMovers: document.querySelector("#premarket-movers"),
  premarketEmpty: document.querySelector("#premarket-empty"),
};

let sequentialPayload = null;
let marketUpdatedAt = null;
let marketAgeTimer = null;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const motionState = {
  alerts: new Map(),
  futures: new Map(),
  movers: new Map(),
  alertCount: null,
  hasAlerts: false,
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

function industryText(industry) {
  return `產業｜${industry || "未分類"}`;
}

function displayMarket(market) {
  return market === "台股個股期貨標的" ? "台股" : (market || "市場");
}

function makeTodayChange(value) {
  const percentage = Number(value);
  if (!Number.isFinite(percentage)) return null;
  const chip = document.createElement("span");
  chip.className = `today-change ${percentage > 0 ? "up" : percentage < 0 ? "down" : "flat"}`;
  chip.textContent = `今日漲跌：${formatSigned(percentage)}%`;
  return chip;
}

function makeAlertCard(alert, motion = {}) {
  const card = document.createElement("article");
  card.className = `alert-card${motion.enter ? " is-fresh" : ""}${motion.isNew ? " is-new" : ""}${motion.isUpdated ? " is-updated" : ""}`;

  const top = document.createElement("div");
  top.className = "alert-top";
  const name = document.createElement("div");
  const ticker = document.createElement("h3");
  ticker.className = "ticker";
  ticker.textContent = alert.symbol;
  const exchange = document.createElement("p");
  exchange.className = "exchange";
  exchange.textContent = [alert.exchange, industryText(alert.industry), alert.bar_time_et].filter(Boolean).join(" · ");
  name.append(ticker, exchange);
  const drop = document.createElement("div");
  drop.className = "drop matrix-number";
  drop.textContent = `${Number(alert.price_change_pct).toFixed(2)}%`;
  if (motion.isUpdated || motion.enter) {
    const start = motion.isUpdated
      ? motion.previous.price_change_pct
      : initialNumberStart(alert.price_change_pct, "down", true);
    animateNumber(drop, start, alert.price_change_pct, (value) => `${value.toFixed(2)}%`);
  }
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
  const priorCount = motionState.alertCount;
  elements.count.classList.add("matrix-number");
  const countStart = motionState.hasAlerts && Number.isFinite(priorCount) ? priorCount : 0;
  animateNumber(elements.count, countStart, alerts.length, (value) => String(Math.round(value)));
  elements.updated.textContent = payload.updated_at_utc ? formatTaipei(payload.updated_at_utc) : "—";
  elements.coverage.textContent = `已掃描 ${String(payload.scanned_symbols || 0)} 檔`;
  elements.source.textContent = payload.source || "";
  elements.alerts.replaceChildren(
    ...alerts.map((alert) => {
      const previous = motionState.alerts.get(alert.symbol);
      const motion = { ...quoteMotion(previous, alert, !motionState.hasAlerts), previous };
      return makeAlertCard(alert, motion);
    })
  );
  elements.empty.hidden = alerts.length !== 0;
  motionState.alerts = quoteSnapshot(alerts, "symbol");
  motionState.alertCount = alerts.length;
  motionState.hasAlerts = true;
}

function makeSparkline(values, direction, animate = false, options = {}) {
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
  industry.textContent = [mover.exchange, industryText(mover.industry), mover.bar_time_et].filter(Boolean).join(" · ");
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

const sentimentMetrics = [
  {
    id: "index",
    label: "加權指數 TAIEX",
    key: "index_close",
    changeKey: "index_daily_change",
    format: (value) => new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 }).format(Number(value)),
    unit: "點",
  },
  {
    id: "short",
    label: "外資台指期未平倉空單",
    key: "foreign_short_open_interest",
    changeKey: "foreign_short_daily_change",
    format: (value) => new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 }).format(Number(value)),
    unit: "口・未平倉",
  },
  {
    id: "margin",
    label: "上市融資餘額",
    key: "margin_balance_100m",
    changeKey: "margin_daily_change_100m",
    format: (value) => Number(value).toLocaleString("zh-TW", { maximumFractionDigits: 1 }),
    unit: "億元",
  },
  {
    id: "vix",
    label: "VIX",
    key: "vix_close",
    changeKey: "vix_daily_change",
    format: (value) => Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 }),
    unit: "美股日線收盤",
  },
];

function sentimentPoints(payload) {
  const points = Array.isArray(payload && payload.points) ? payload.points : [];
  return points.filter((point) => sentimentMetrics.every((metric) => Number.isFinite(Number(point[metric.key]))));
}

function sentimentDelta(value, metric) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "日增減 —";
  const sign = number > 0 ? "+" : "";
  return `日增減 ${sign}${metric.format(number)} ${metric.id === "index" ? "點" : metric.id === "short" ? "口" : metric.id === "margin" ? "億" : ""}`.trim();
}

function makeSentimentKpi(metric, point, liveIndex) {
  const card = document.createElement("article");
  card.className = `sentiment-kpi ${metric.id}`;
  const label = document.createElement("p");
  const useLiveIndex = metric.id === "index" && Number.isFinite(Number(liveIndex && liveIndex.price));
  label.textContent = useLiveIndex ? "加權指數 TAIEX｜最新報價" : metric.label;
  const value = document.createElement("strong");
  value.className = "matrix-number";
  value.textContent = metric.format(useLiveIndex ? liveIndex.price : point[metric.key]);
  const unit = document.createElement("span");
  unit.className = "sentiment-unit";
  unit.textContent = useLiveIndex && liveIndex.timestamp
    ? `報價時間：${formatTaipeiTimestamp(liveIndex.timestamp)}`
    : metric.unit;
  const delta = document.createElement("small");
  const deltaValue = Number(useLiveIndex ? liveIndex.change : point[metric.changeKey]);
  delta.className = `sentiment-delta ${deltaValue > 0 ? "up" : deltaValue < 0 ? "down" : "flat"}`;
  delta.textContent = sentimentDelta(deltaValue, metric);
  card.append(label, value, unit, delta);
  return card;
}

function formatSentimentTooltipValue(metric, point) {
  if (!Number.isFinite(Number(point[metric.key]))) return "盤後資料尚未公布";
  const value = `${metric.format(point[metric.key])} ${metric.unit}`;
  const delta = sentimentDelta(point[metric.changeKey], metric);
  return `${value}｜${delta}`;
}

function makeTaiwanSentimentChart(points) {
  if (points.length < 2) {
    const empty = document.createElement("p");
    empty.className = "sentiment-empty";
    empty.textContent = "等待交易所公布足夠的日資料後建立關聯圖。";
    return empty;
  }

  const namespace = "http://www.w3.org/2000/svg";
  const width = 1000;
  const height = 360;
  const plot = { left: 64, right: 24, top: 22, bottom: 46 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const normalized = new Map();
  for (const metric of sentimentMetrics) {
    const baseline = Number(points[0][metric.key]);
    normalized.set(metric.id, points.map((point) => (Number(point[metric.key]) / baseline) * 100));
  }
  const allValues = [...normalized.values()].flat();
  const low = Math.min(...allValues);
  const high = Math.max(...allValues);
  const padding = Math.max((high - low) * 0.14, 1.8);
  const axisMin = Math.floor((low - padding) * 2) / 2;
  const axisMax = Math.ceil((high + padding) * 2) / 2;
  const xFor = (index) => plot.left + (index / (points.length - 1)) * plotWidth;
  const yFor = (value) => plot.top + ((axisMax - value) / (axisMax - axisMin)) * plotHeight;

  const wrap = document.createElement("div");
  wrap.className = "sentiment-chart-canvas";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "台股槓桿與風險的標準化關聯圖，游標可查看各日原始數值。 ");

  for (let tick = 0; tick <= 4; tick += 1) {
    const value = axisMin + ((axisMax - axisMin) * tick) / 4;
    const y = yFor(value);
    const line = document.createElementNS(namespace, "line");
    line.setAttribute("class", "sentiment-grid");
    line.setAttribute("x1", String(plot.left));
    line.setAttribute("x2", String(width - plot.right));
    line.setAttribute("y1", String(y));
    line.setAttribute("y2", String(y));
    svg.append(line);
    const label = document.createElementNS(namespace, "text");
    label.setAttribute("class", "sentiment-axis-label");
    label.setAttribute("x", "8");
    label.setAttribute("y", String(y + 4));
    label.textContent = value.toFixed(1);
    svg.append(label);
  }

  const xLabelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  for (const index of xLabelIndexes) {
    const label = document.createElementNS(namespace, "text");
    label.setAttribute("class", "sentiment-axis-label sentiment-date-label");
    label.setAttribute("x", String(xFor(index)));
    label.setAttribute("y", String(height - 15));
    label.textContent = String(points[index].date || "").slice(5).replace("-", "/");
    svg.append(label);
  }

  const paths = new Map();
  const dots = new Map();
  for (const metric of sentimentMetrics) {
    const values = normalized.get(metric.id) || [];
    const path = document.createElementNS(namespace, "path");
    path.setAttribute("class", `sentiment-line ${metric.id}`);
    path.setAttribute("d", values.map((value, index) => `${index ? "L" : "M"}${xFor(index)} ${yFor(value)}`).join(" "));
    svg.append(path);
    paths.set(metric.id, values);
    const dot = document.createElementNS(namespace, "circle");
    dot.setAttribute("class", `sentiment-hover-dot ${metric.id}`);
    dot.setAttribute("r", "5");
    dot.hidden = true;
    svg.append(dot);
    dots.set(metric.id, dot);
  }

  const hoverLine = document.createElementNS(namespace, "line");
  hoverLine.setAttribute("class", "sentiment-hover-line");
  hoverLine.setAttribute("y1", String(plot.top));
  hoverLine.setAttribute("y2", String(height - plot.bottom));
  hoverLine.hidden = true;
  svg.append(hoverLine);
  const capture = document.createElementNS(namespace, "rect");
  capture.setAttribute("x", String(plot.left));
  capture.setAttribute("y", String(plot.top));
  capture.setAttribute("width", String(plotWidth));
  capture.setAttribute("height", String(plotHeight));
  capture.setAttribute("fill", "transparent");
  capture.setAttribute("class", "sentiment-capture");
  svg.append(capture);

  const tooltip = document.createElement("div");
  tooltip.className = "sentiment-tooltip";
  tooltip.hidden = true;
  const showPoint = (index, clientX) => {
    const point = points[index];
    const x = xFor(index);
    hoverLine.hidden = false;
    hoverLine.setAttribute("x1", String(x));
    hoverLine.setAttribute("x2", String(x));
    for (const metric of sentimentMetrics) {
      const dot = dots.get(metric.id);
      const values = paths.get(metric.id) || [];
      dot.hidden = false;
      dot.setAttribute("cx", String(x));
      dot.setAttribute("cy", String(yFor(values[index])));
    }
    const date = document.createElement("strong");
    date.textContent = point.date || "";
    const lines = sentimentMetrics.map((metric) => {
      const line = document.createElement("span");
      line.className = metric.id;
      line.textContent = `${metric.label}：${formatSentimentTooltipValue(metric, point)}`;
      return line;
    });
    tooltip.replaceChildren(date, ...lines);
    tooltip.hidden = false;
    const bounds = svg.getBoundingClientRect();
    const percentage = clientX === undefined ? (x / width) * 100 : ((clientX - bounds.left) / bounds.width) * 100;
    tooltip.style.left = `${Math.max(8, Math.min(92, percentage))}%`;
  };
  const hidePoint = () => {
    tooltip.hidden = true;
    hoverLine.hidden = true;
    for (const dot of dots.values()) dot.hidden = true;
  };
  capture.addEventListener("pointermove", (event) => {
    const bounds = svg.getBoundingClientRect();
    const relative = Math.max(0, Math.min(1, (event.clientX - bounds.left - (plot.left / width) * bounds.width) / ((plotWidth / width) * bounds.width)));
    showPoint(Math.round(relative * (points.length - 1)), event.clientX);
  });
  capture.addEventListener("pointerleave", hidePoint);
  wrap.append(svg, tooltip);
  return wrap;
}

function formatTaipeiTimestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "時間待更新";
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function sentimentChartPoints(points, liveIndex) {
  if (!Number.isFinite(Number(liveIndex && liveIndex.price))) return points;
  const liveDate = String(liveIndex.date || "");
  const last = points.at(-1);
  if (!liveDate || !last) return points;
  if (liveDate === last.date) {
    return [...points.slice(0, -1), {
      ...last,
      index_close: Number(liveIndex.price),
      index_daily_change: liveIndex.change,
      index_live: true,
    }];
  }
  if (liveDate > last.date) {
    return [...points, {
      date: liveDate,
      index_close: Number(liveIndex.price),
      index_daily_change: liveIndex.change,
      index_live: true,
    }];
  }
  return points;
}

function scaleSentimentLane(points, metric) {
  const values = points
    .map((point) => Number(point[metric.key]))
    .filter((value) => Number.isFinite(value));
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const spread = Math.max(maximum - minimum, Math.max(Math.abs(maximum) * 0.035, 1));
  return { min: minimum - spread * 0.16, max: maximum + spread * 0.16 };
}

function sentimentLinePath(points, metric, xFor, yFor) {
  let path = "";
  let connected = false;
  for (const point of points) {
    const value = Number(point[metric.key]);
    if (!Number.isFinite(value)) {
      connected = false;
      continue;
    }
    path += `${connected ? "L" : "M"}${xFor(point)} ${yFor(value)} `;
    connected = true;
  }
  return path.trim();
}

function makeTaiwanRelationshipPanel(points, metric) {
  const namespace = "http://www.w3.org/2000/svg";
  const width = 620;
  const height = 262;
  const plot = { left: 72, right: 18, top: 24, bottom: 38 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const scale = scaleSentimentLane(points, metric);
  const xFor = (index) => plot.left + (index / (points.length - 1)) * plotWidth;
  const yFor = (value) => plot.top + ((scale.max - value) / (scale.max - scale.min)) * plotHeight;
  const latest = [...points].reverse().find((point) => Number.isFinite(Number(point[metric.key])));

  const panel = document.createElement("article");
  panel.className = `sentiment-panel ${metric.id}`;
  const heading = document.createElement("div");
  heading.className = "sentiment-panel-heading";
  const title = document.createElement("h3");
  title.textContent = metric.label;
  const value = document.createElement("strong");
  value.className = "matrix-number";
  value.textContent = latest ? metric.format(latest[metric.key]) : "—";
  heading.append(title, value);

  const canvas = document.createElement("div");
  canvas.className = "sentiment-chart-canvas relationship-panel";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${metric.label}獨立刻度走勢圖；游標可查看每日原始數值。`);

  const background = document.createElementNS(namespace, "rect");
  background.setAttribute("class", `sentiment-lane ${metric.id}`);
  background.setAttribute("x", String(plot.left));
  background.setAttribute("y", String(plot.top));
  background.setAttribute("width", String(plotWidth));
  background.setAttribute("height", String(plotHeight));
  svg.append(background);

  for (let tick = 0; tick <= 3; tick += 1) {
    const tickValue = scale.min + ((scale.max - scale.min) * tick) / 3;
    const y = yFor(tickValue);
    const grid = document.createElementNS(namespace, "line");
    grid.setAttribute("class", "sentiment-grid");
    grid.setAttribute("x1", String(plot.left));
    grid.setAttribute("x2", String(width - plot.right));
    grid.setAttribute("y1", String(y));
    grid.setAttribute("y2", String(y));
    svg.append(grid);
    const axis = document.createElementNS(namespace, "text");
    axis.setAttribute("class", "sentiment-axis-label");
    axis.setAttribute("x", String(plot.left - 9));
    axis.setAttribute("y", String(y + 4));
    axis.setAttribute("text-anchor", "end");
    axis.textContent = metric.format(tickValue);
    svg.append(axis);
  }

  const xLabels = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  for (const index of xLabels) {
    const label = document.createElementNS(namespace, "text");
    label.setAttribute("class", "sentiment-axis-label sentiment-date-label");
    label.setAttribute("x", String(xFor(index)));
    label.setAttribute("y", String(height - 12));
    label.textContent = String(points[index].date || "").slice(5).replace("-", "/");
    svg.append(label);
  }

  const path = document.createElementNS(namespace, "path");
  path.setAttribute("class", `sentiment-line ${metric.id}`);
  let connected = false;
  const pathData = points.map((point, index) => {
    const pointValue = Number(point[metric.key]);
    if (!Number.isFinite(pointValue)) {
      connected = false;
      return "";
    }
    const command = connected ? "L" : "M";
    connected = true;
    return `${command}${xFor(index)} ${yFor(pointValue)}`;
  }).join(" ");
  path.setAttribute("d", pathData);
  svg.append(path);

  const hoverLine = document.createElementNS(namespace, "line");
  hoverLine.setAttribute("class", "sentiment-hover-line");
  hoverLine.setAttribute("y1", String(plot.top));
  hoverLine.setAttribute("y2", String(height - plot.bottom));
  hoverLine.hidden = true;
  svg.append(hoverLine);
  const dot = document.createElementNS(namespace, "circle");
  dot.setAttribute("class", `sentiment-hover-dot ${metric.id}`);
  dot.setAttribute("r", metric.id === "index" ? "5.5" : "4.5");
  dot.hidden = true;
  svg.append(dot);

  const capture = document.createElementNS(namespace, "rect");
  capture.setAttribute("x", String(plot.left));
  capture.setAttribute("y", String(plot.top));
  capture.setAttribute("width", String(plotWidth));
  capture.setAttribute("height", String(plotHeight));
  capture.setAttribute("fill", "transparent");
  capture.setAttribute("class", "sentiment-capture");
  svg.append(capture);

  const tooltip = document.createElement("div");
  tooltip.className = "sentiment-tooltip single-metric";
  tooltip.hidden = true;
  const showPoint = (index, clientX) => {
    const point = points[index];
    const pointValue = Number(point[metric.key]);
    if (!Number.isFinite(pointValue)) return;
    const x = xFor(index);
    hoverLine.hidden = false;
    hoverLine.setAttribute("x1", String(x));
    hoverLine.setAttribute("x2", String(x));
    dot.hidden = false;
    dot.setAttribute("cx", String(x));
    dot.setAttribute("cy", String(yFor(pointValue)));
    const date = document.createElement("strong");
    date.textContent = point.index_live && metric.id === "index" ? `${point.date}｜最新報價` : point.date || "";
    const detail = document.createElement("span");
    detail.className = metric.id;
    detail.textContent = formatSentimentTooltipValue(metric, point);
    tooltip.replaceChildren(date, detail);
    tooltip.hidden = false;
    const bounds = svg.getBoundingClientRect();
    const percentage = ((clientX - bounds.left) / bounds.width) * 100;
    tooltip.style.left = `${Math.max(15, Math.min(85, percentage))}%`;
  };
  const hidePoint = () => {
    tooltip.hidden = true;
    hoverLine.hidden = true;
    dot.hidden = true;
  };
  capture.addEventListener("pointermove", (event) => {
    const bounds = svg.getBoundingClientRect();
    const relative = Math.max(0, Math.min(1, (event.clientX - bounds.left - (plot.left / width) * bounds.width) / ((plotWidth / width) * bounds.width)));
    showPoint(Math.round(relative * (points.length - 1)), event.clientX);
  });
  capture.addEventListener("pointerleave", hidePoint);
  canvas.append(svg, tooltip);
  panel.append(heading, canvas);
  return panel;
}

function makeTaiwanRelationshipChart(points, liveIndex) {
  if (points.length < 2) return makeTaiwanSentimentChart(points);
  const chartPoints = sentimentChartPoints(points, liveIndex);
  const grid = document.createElement("div");
  grid.className = "sentiment-chart-grid";
  grid.append(...sentimentMetrics.map((metric) => makeTaiwanRelationshipPanel(chartPoints, metric)));
  return grid;
}

function renderTaiwanSentiment(payload) {
  const points = sentimentPoints(payload);
  elements.taiwanSentimentUpdated.textContent = points.length
    ? `${payload.label || "年初至今"}｜籌碼最後 ${points.at(-1).date}`
    : "資料更新中";
  elements.taiwanSentimentSource.textContent = payload && payload.source
    ? `${payload.source}｜四個獨立刻度共用同一時間軸；籌碼資料為盤後統計，並非即時逐筆。`
    : "";
  if (points.length === 0) {
    const empty = document.createElement("p");
    empty.className = "sentiment-empty";
    empty.textContent = "等待期交所、證交所與日線資料同步後顯示。";
    elements.taiwanSentimentKpis.replaceChildren();
    elements.taiwanSentimentChart.replaceChildren(empty);
    return;
  }
  const latest = points.at(-1);
  elements.taiwanSentimentKpis.replaceChildren(...sentimentMetrics.map((metric) => makeSentimentKpi(metric, latest, payload.live_index)));
  elements.taiwanSentimentChart.replaceChildren(makeTaiwanRelationshipChart(points, payload.live_index));
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

  renderTaiwanSentiment(payload.taiwan_sentiment || {});

  const premarket = payload.premarket || {};
  const movers = Array.isArray(premarket.movers) ? premarket.movers : [];
  const threshold = Number(premarket.threshold_pct || 2);
  elements.premarketSummary.textContent = premarket.active
    ? `美東盤前中 · 已掃描 ${Number(premarket.scanned_symbols || 0)} 檔 · 異常門檻 ±${threshold}%`
    : "僅於美東 04:00–09:30 掃描";
  const binanceCount = Number(premarket.binance_equity_scanned_symbols || 0);
  if (premarket.binance_equity_enabled && binanceCount > 0) {
    elements.premarketSummary.textContent += `｜Binance 股票 USDT 合約監控 ${binanceCount} 檔`;
  }
  elements.premarketMovers.replaceChildren(
    ...movers.map((mover) => {
      const previous = motionState.movers.get(mover.symbol);
      const motion = { ...quoteMotion(previous, mover, !motionState.hasMarket), previous };
      return makePremarketCard(mover, motion);
    })
  );
  elements.premarketEmpty.hidden = movers.length !== 0;
  if (movers.length === 0) {
    elements.premarketEmpty.textContent = premarket.active
      ? `目前沒有指標股達到 ±${threshold}% 的盤前異常門檻。`
      : "目前非美股盤前時段；下一個盤前時段會自動更新。";
  }
  motionState.futures = quoteSnapshot(futures, "key");
  motionState.movers = quoteSnapshot(movers, "symbol");
  motionState.hasMarket = true;
}

function formatShares(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 }).format(Math.abs(number) / 1000)} 張`;
}

function formatPercent(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? `${formatSigned(number, digits)}%` : "—";
}

function makeChipKpi(label, value, detail, tone = "") {
  const card = document.createElement("article");
  card.className = `chip-kpi ${tone}`.trim();
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value;
  const detailNode = document.createElement("small");
  detailNode.textContent = detail;
  card.append(labelNode, valueNode, detailNode);
  return card;
}

function makeChipFact(label, value) {
  const fact = document.createElement("div");
  fact.className = "chip-fact";
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("b");
  valueNode.textContent = value;
  fact.append(labelNode, valueNode);
  return fact;
}

function makeChipCandidate(candidate) {
  const card = document.createElement("article");
  card.className = `chip-candidate${candidate.qualified ? " qualified" : ""}`;

  const top = document.createElement("div");
  top.className = "chip-candidate-top";
  const titleGroup = document.createElement("div");
  const title = document.createElement("h4");
  title.textContent = `${candidate.symbol} ${candidate.name || ""}`.trim();
  const subtitle = document.createElement("p");
  subtitle.className = "chip-candidate-name";
  subtitle.textContent = `${industryText(candidate.industry)} · ${candidate.exchange || "TWSE"}`;
  titleGroup.append(title, subtitle);
  const score = document.createElement("span");
  score.className = "chip-score";
  score.textContent = `分數 ${Number(candidate.score || 0).toFixed(1)}`;
  top.append(titleGroup, score);

  const priceRow = document.createElement("div");
  priceRow.className = "chip-candidate-price";
  const price = document.createElement("strong");
  price.textContent = formatMarketPrice(candidate.last_price, "TWD");
  const today = makeTodayChange(candidate.today_change_pct);
  priceRow.append(price);
  if (today) priceRow.append(today);

  const facts = document.createElement("div");
  facts.className = "chip-facts";
  const foreignDirection = Number(candidate.foreign_5_shares) >= 0 ? "+" : "−";
  const trustDirection = Number(candidate.trust_5_shares) >= 0 ? "+" : "−";
  facts.append(
    makeChipFact("外資近 5 日", `${foreignDirection}${formatShares(candidate.foreign_5_shares)}`),
    makeChipFact("投信近 5 日", `${trustDirection}${formatShares(candidate.trust_5_shares)}`),
    makeChipFact("大戶持股 12–15", Number.isFinite(Number(candidate.large_holder_pct)) ? `${Number(candidate.large_holder_pct).toFixed(2)}%` : "等待資料"),
    makeChipFact("大戶週增減", Number.isFinite(Number(candidate.large_holder_weekly_change_pct)) ? formatPercent(candidate.large_holder_weekly_change_pct, 3) : "等待下週快照")
  );

  const values = (Array.isArray(candidate.sparkline) ? candidate.sparkline : []).map(Number).filter(Number.isFinite);
  const direction = values.length >= 2 && values.at(-1) < values[0] ? "down" : "up";
  const sparkline = makeSparkline(values, direction, true, {
    title: "最近 30 個交易日收盤走勢",
  });
  if (sparkline) sparkline.classList.add("signal-sparkline");

  const foot = document.createElement("div");
  foot.className = "chip-card-foot";
  const status = document.createElement("span");
  status.textContent = candidate.qualified
    ? `法人連續：外資 ${Number(candidate.foreign_positive_days || 0)}/5、投信 ${Number(candidate.trust_positive_days || 0)}/5；${candidate.above_ma20 ? "站上" : "跌破"} 20 日均線`
    : "分數未達目前觀察門檻；保留作相對比較。";
  foot.append(status, makeTradingViewLink(candidate, "D"));
  card.append(top, priceRow, facts);
  if (sparkline) card.append(sparkline);
  card.append(foot);
  return card;
}

function renderChipBacktest(backtest) {
  const panel = document.createElement("article");
  panel.className = "chip-backtest";
  const head = document.createElement("div");
  head.className = "chip-backtest-head";
  const title = document.createElement("h3");
  title.textContent = "基準模型回測・下一交易日開盤至第 5 日收盤";
  const avg = Number(backtest && backtest.average_return_5d_pct);
  const winRate = Number(backtest && backtest.win_rate_pct);
  const validated = Boolean(backtest && backtest.ready && avg > 0 && winRate >= 50);
  const status = document.createElement("p");
  status.className = `chip-backtest-status${validated ? " valid" : ""}`;
  status.textContent = validated ? "樣本內暫時通過" : "目前未通過驗證";
  head.append(title, status);
  const explanation = document.createElement("p");
  if (!backtest || !backtest.ready) {
    explanation.textContent = (backtest && backtest.reason) || "正在累積足夠的法人歷史資料後才能計算回測。";
  } else if (!validated) {
    explanation.textContent = "目前基準模型的 5 日平均報酬或勝率未達驗證門檻；因此下方僅是籌碼觀察名單，不標示為「可能發動」。模型會持續保留資料，之後再做樣本外驗證。";
  } else {
    explanation.textContent = "基準模型在目前樣本中暫時為正，但仍須以樣本外、不同盤勢與交易成本測試，不能視為投資建議。";
  }
  const metrics = document.createElement("div");
  metrics.className = "chip-backtest-metrics";
  if (backtest && backtest.ready) {
    metrics.append(
      Object.assign(document.createElement("span"), { textContent: `樣本訊號：${Number(backtest.signals || 0)}` }),
      Object.assign(document.createElement("span"), { textContent: `勝率：${Number(backtest.win_rate_pct || 0).toFixed(1)}%` }),
      Object.assign(document.createElement("span"), { textContent: `5 日平均：${formatPercent(backtest.average_return_5d_pct)}` }),
      Object.assign(document.createElement("span"), { textContent: `中位數：${formatPercent(backtest.median_return_5d_pct)}` }),
      Object.assign(document.createElement("span"), { textContent: `期間：${backtest.period_start || "—"} 至 ${backtest.period_end || "—"}` })
    );
  }
  panel.append(head, explanation, metrics);
  return panel;
}

function renderChipRadar(payload) {
  if (!payload || !elements.chipRadarSummary) return;
  const backtest = payload.backtest || {};
  const average = Number(backtest.average_return_5d_pct);
  const holder = payload.holder_snapshot || {};
  const backtestTone = backtest.ready && average > 0 && Number(backtest.win_rate_pct) >= 50 ? "positive" : "warning";
  const backtestValue = backtest.ready ? formatPercent(average) : "資料累積中";
  elements.chipRadarUpdated.textContent = payload.updated_at_utc
    ? `資料更新：${formatTaipei(payload.updated_at_utc)}`
    : "等待籌碼資料";
  elements.chipRadarSummary.replaceChildren(
    makeChipKpi("符合目前觀察門檻", `${Number(payload.qualified_candidates || 0)} 檔`, `${payload.universe_label || "台股觀察名單"} · 已取得價格 ${Number(payload.priced_symbols || 0)} 檔`, "positive"),
    makeChipKpi("TDCC 大戶資料", holder.as_of || "等待資料", holder.available ? "持股分級 12–15 已讀取；週增減需下週快照" : "官方週資料暫時不可用"),
    makeChipKpi("基準回測 5 日平均", backtestValue, backtest.ready ? `勝率 ${Number(backtest.win_rate_pct || 0).toFixed(1)}% · 訊號 ${Number(backtest.signals || 0)} 筆` : "尚未有足夠完整樣本", backtestTone)
  );
  elements.chipRadarBacktest.replaceChildren(renderChipBacktest(backtest));
  elements.chipRadarSource.textContent = payload.source || "";
  const candidates = Array.isArray(payload.candidates) ? payload.candidates : [];
  if (candidates.length === 0) {
    const empty = document.createElement("p");
    empty.className = "timeframe-empty";
    empty.textContent = "目前沒有可呈現的籌碼觀察資料。";
    elements.chipRadarCandidates.replaceChildren(empty);
  } else {
    elements.chipRadarCandidates.replaceChildren(...candidates.map(makeChipCandidate));
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
  const age = document.createElement("p");
  age.className = "signal-age";
  age.textContent = Number(signal.age_bars) === 0 ? "最新已完成 K 棒" : `${signal.age_bars} 根 K 棒前`;
  heading.append(ticker, age);

  const price = document.createElement("strong");
  price.className = "signal-price";
  price.textContent = formatCurrency(signal.last_price);
  const quote = document.createElement("div");
  quote.className = "signal-quote";
  quote.append(price);
  const todayChange = makeTodayChange(signal.today_change_pct);
  if (todayChange) quote.append(todayChange);
  top.append(heading, quote);

  const details = document.createElement("div");
  details.className = "signal-details";
  const industry = document.createElement("span");
  industry.textContent = industryText(signal.industry);
  const occurred = document.createElement("span");
  occurred.textContent = `訊號產生：${signal.bar_time_et || "資料不足"}`;
  details.append(industry, occurred);

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
    title: "最近 30 根已完成 K 棒走勢；圓點為 TD 訊號",
    markerIndex: signal.sparkline_signal_index,
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
  const selectedMarket = elements.sequentialMarket.value;
  const multiplier = elements.sequentialSort.value === "oldest" ? 1 : -1;
  const signals = (Array.isArray(frame.trend_reclaim_signals) ? frame.trend_reclaim_signals : [])
    .filter((signal) => signal.side === "buy" && signal.signal_type === "long_reclaim");
  return signals
    .filter((signal) => selectedMarket === "all" || displayMarket(signal.market) === selectedMarket)
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
  price.textContent = formatCurrency(signal.last_price);
  const quote = document.createElement("div");
  quote.className = "signal-quote";
  quote.append(price);
  const todayChange = makeTodayChange(signal.today_change_pct);
  if (todayChange) quote.append(todayChange);
  top.append(heading, quote);

  const details = document.createElement("div");
  details.className = "signal-details";
  const industry = document.createElement("span");
  industry.textContent = industryText(signal.industry);
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
  count.textContent = `最近 ${Number(frame.recent_bars || 5)} 根：${signals.length} 個`;
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

function filteredSignals(frame) {
  const selectedMarket = elements.sequentialMarket.value;
  const selectedSide = elements.sequentialSide.value;
  const selectedMomentum = elements.sequentialMomentum.value;
  const multiplier = elements.sequentialSort.value === "oldest" ? 1 : -1;
  const signals = Array.isArray(frame.signals) ? frame.signals : [];
  return signals
    .filter((signal) => selectedMarket === "all" || displayMarket(signal.market) === selectedMarket)
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
  renderTrendReclaims(frames);
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
    const [alerts, sequential, market, chipRadar] = await Promise.all([
      loadJson("data/alerts.json"),
      loadJson("data/sequential.json"),
      loadJson("data/market.json"),
      loadJson("data/chip_radar.json"),
    ]);
    renderSelloff(alerts);
    renderSequential(sequential);
    renderMarketPulse(market);
    renderChipRadar(chipRadar);
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
