const elements = {
  status: document.querySelector("#market-status"),
  count: document.querySelector("#alert-count"),
  updated: document.querySelector("#updated-at"),
  coverage: document.querySelector("#scan-coverage"),
  alerts: document.querySelector("#alerts"),
  empty: document.querySelector("#empty"),
  source: document.querySelector("#source-note"),
  refresh: document.querySelector("#refresh"),
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

function formatTaipei(value) {
  return new Intl.DateTimeFormat("zh-TW", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Asia/Taipei",
  }).format(new Date(value));
}

function text(label, value) {
  const node = document.createElement("span");
  node.textContent = label;
  const number = document.createElement("strong");
  number.textContent = value;
  return [node, number];
}

function makeStat(label, value) {
  const box = document.createElement("div");
  box.className = "stat";
  box.append(...text(label, value));
  return box;
}

function tradingViewUrl(alert) {
  const symbol = String(alert.symbol || "").replace(/[^A-Z0-9.-]/g, "");
  const exchange = String(alert.exchange || "NASDAQ").replace(/[^A-Z]/g, "");
  return "https://www.tradingview.com/chart/?symbol=" + encodeURIComponent(exchange + ":" + symbol);
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
  exchange.textContent = alert.exchange + " · " + alert.bar_time_et;
  name.append(ticker, exchange);
  const drop = document.createElement("div");
  drop.className = "drop";
  drop.textContent = Number(alert.price_change_pct).toFixed(2) + "%";
  top.append(name, drop);

  const stats = document.createElement("div");
  stats.className = "stats";
  stats.append(
    makeStat("最新價格", formatCurrency(alert.last_price)),
    makeStat("5 分鐘量比", Number(alert.volume_multiple).toFixed(2) + "×"),
    makeStat("近 4 日日均成交額", formatCompactCurrency(alert.average_daily_dollar_volume))
  );

  const link = document.createElement("a");
  link.className = "tv-link";
  link.href = tradingViewUrl(alert);
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "在 TradingView 開啟圖表";
  card.append(top, stats, link);
  return card;
}

function render(payload) {
  const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
  const open = payload.market_status === "open";
  elements.status.textContent = open ? "美股一般盤監控中" : "美股一般盤外";
  elements.status.style.color = open ? "var(--accent)" : "var(--muted)";
  elements.count.textContent = String(alerts.length);
  elements.updated.textContent = payload.updated_at_utc ? formatTaipei(payload.updated_at_utc) : "—";
  elements.coverage.textContent = "已掃描 " + String(payload.scanned_symbols || 0) + " 檔";
  elements.source.textContent = payload.source || "";
  elements.alerts.replaceChildren(...alerts.map(makeAlertCard));
  elements.empty.hidden = alerts.length !== 0;
}

async function refresh() {
  elements.refresh.disabled = true;
  elements.refresh.textContent = "更新中";
  try {
    const response = await fetch("data/alerts.json?cache=" + Date.now(), { cache: "no-store" });
    if (!response.ok) throw new Error("無法讀取警示資料");
    render(await response.json());
  } catch (error) {
    elements.status.textContent = "暫時無法載入";
    elements.source.textContent = "請稍後重新整理，或檢查 GitHub Actions 是否成功完成。";
    console.error(error);
  } finally {
    elements.refresh.disabled = false;
    elements.refresh.textContent = "重新整理";
  }
}

elements.refresh.addEventListener("click", refresh);
refresh();
setInterval(refresh, 60_000);
