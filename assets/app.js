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
  const code = currency === "TWD" ? "TWD" : "USD";
  return new Intl.NumberFormat(code === "TWD" ? "zh-TW" : "en-US", {
    style: "currency",
    currency: code,
    maximumFractionDigits: code === "TWD" ? 0 : 2,
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
  const query = new URLSearchParams({ symbol: `${exchange}:${symbol}` });
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

function makeFutureCard(future) {
  const available = !future.unavailable && Number.isFinite(Number(future.last_price));
  const change = Number(future.change_pct || 0);
  const direction = change > 0 ? "up" : change < 0 ? "down" : "flat";
  const card = document.createElement("article");
  card.className = `future-card ${available ? direction : "unavailable"}`;

  const label = document.createElement("p");
  label.className = "future-label";
  label.textContent = future.label || future.ticker;
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
    ? "期指指數替代報價"
    : future.as_of_utc
      ? `資料時間 · ${formatTaipei(future.as_of_utc)}`
      : "等待下一次更新";
  card.append(label, price, movement, metadata);

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
  details.textContent = `盤前 ${formatMarketPrice(mover.last_price, "USD")}｜昨收 ${formatMarketPrice(mover.previous_close, "USD")}`;
  card.append(top, details, makeTradingViewLink(mover, "5", "在 TradingView 檢視"));
  return card;
}

function renderMarketPulse(payload) {
  const futures = Array.isArray(payload.futures) ? payload.futures : [];
  elements.futuresStrip.replaceChildren(...futures.map(makeFutureCard));
  elements.marketPulseUpdated.textContent = payload.updated_at_utc
    ? `資料更新 · ${formatTaipei(payload.updated_at_utc)}`
    : "等待下一次更新";

  const premarket = payload.premarket || {};
  const movers = Array.isArray(premarket.movers) ? premarket.movers : [];
  const threshold = Number(premarket.threshold_pct || 2);
  elements.premarketSummary.textContent = premarket.active
    ? `美東盤前中 · 已掃描 ${Number(premarket.scanned_symbols || 0)} 檔 · 異常門檻 ±${threshold}%`
    : "僅於美東 04:00–09:30 掃描";
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
    const zoneText = {
      below_band: "跌破趨勢帶下方",
      lower_edge: "位於趨勢帶下緣",
      not_lower: "未在趨勢帶下緣",
    }[momentum.zone_position] || "趨勢帶資料不足";
    const priorBars = Number(momentum.prior_window_bars || 0);
    const priorCount = Number(momentum.prior_bearish_count || 0);
    const breakdownBars = Number(momentum.breakdown_bars_ago);
    const breakdownText = Number.isFinite(breakdownBars)
      ? `先前 ${breakdownBars} K 已跌破趨勢帶`
      : `近 ${Number(momentum.breakdown_lookback_bars || 0)} K 未找到先行跌破`;
    const tdLocationText = momentum.post_breakdown_td
      ? "TD 位於黃線與趨勢帶下方"
      : `${zoneText}・TD 尚未符合右下方位置`;
    confirmation.textContent = momentum.bearish_confirmed
      ? `空方動能確認：符合｜前 ${priorBars} K 空方動能 ${priorCount} 次・${breakdownText}・${tdLocationText}`
      : `空方動能確認：未完整符合｜前 ${priorBars} K 空方動能 ${priorCount} 次・${breakdownText}・${tdLocationText}`;
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
