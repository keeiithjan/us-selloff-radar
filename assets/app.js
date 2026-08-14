const elements = {
  refresh: document.querySelector("#refresh"),
  sequentialFrames: document.querySelector("#sequential-frames"),
  sequentialUpdated: document.querySelector("#sequential-updated"),
  sequentialSource: document.querySelector("#sequential-source"),
  sequentialMarket: document.querySelector("#sequential-market"),
  sequentialSort: document.querySelector("#sequential-sort"),
  sequentialSide: document.querySelector("#sequential-side"),
  sequentialMomentum: document.querySelector("#sequential-momentum"),
  downloadTradingViewList: document.querySelector("#download-tradingview-list"),
  tradingViewExportNote: document.querySelector("#tradingview-export-note"),
  trendReclaimFrames: document.querySelector("#trend-reclaim-frames"),
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
let marketUpdatedAt = null;
let marketAgeTimer = null;
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

function makeTodayChange(value) {
  const percentage = Number(value);
  if (!Number.isFinite(percentage)) return null;
  const chip = document.createElement("span");
  chip.className = `today-change ${percentage > 0 ? "up" : percentage < 0 ? "down" : "flat"}`;
  chip.textContent = `今日漲跌：${formatSigned(percentage)}%`;
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
  const selectedMarket = elements.sequentialMarket.value;
  const unique = new Map();
  for (const frame of frames) {
    const signals = Array.isArray(frame.signals) ? frame.signals : [];
    for (const signal of signals) {
      if (signal.side !== "buy") continue;
      if (selectedMarket !== "all" && signal.market !== selectedMarket) continue;
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
  elements.sequentialFrames.replaceChildren(...frames.map(makeTimeframe));
  renderTrendReclaims(frames);
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

async function refresh() {
  elements.refresh.disabled = true;
  elements.refresh.textContent = "更新中…";
  try {
    const [sequential, market] = await Promise.all([
      loadJson("data/sequential.json"),
      loadJson("data/market.json"),
    ]);
    renderSequential(sequential);
    renderMarketPulse(market);
  } catch (error) {
    elements.sequentialSource.textContent = "資料讀取失敗；請稍後重試，或查看 GitHub Actions 的最近執行結果。";
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
elements.downloadTradingViewList.addEventListener("click", downloadTradingViewList);
refresh();
setInterval(refresh, 60_000);
