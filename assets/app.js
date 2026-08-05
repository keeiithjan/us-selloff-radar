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
  card.append(top, labels, makeTradingViewLink(signal, interval, "在 TradingView 檢視"));
  return card;
}

function filteredSignals(frame) {
  const selectedMarket = elements.sequentialMarket.value;
  const selectedSide = elements.sequentialSide.value;
  const multiplier = elements.sequentialSort.value === "oldest" ? 1 : -1;
  const signals = Array.isArray(frame.signals) ? frame.signals : [];
  return signals
    .filter((signal) => selectedMarket === "all" || signal.market === selectedMarket)
    .filter((signal) => selectedSide === "all" || signal.side === selectedSide)
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
    const [alerts, sequential] = await Promise.all([
      loadJson("data/alerts.json"),
      loadJson("data/sequential.json"),
    ]);
    renderSelloff(alerts);
    renderSequential(sequential);
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
refresh();
setInterval(refresh, 60_000);
