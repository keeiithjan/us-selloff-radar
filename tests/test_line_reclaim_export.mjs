import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

function fakeNode() {
  return {
    addEventListener() {},
    append(...children) { this.children.push(...children); },
    children: [],
    classList: { add() {}, remove() {}, toggle() {} },
    dataset: {},
    disabled: false,
    hidden: false,
    remove() {},
    replaceChildren() {},
    setAttribute() {},
    style: {},
    textContent: "",
    value: "all",
  };
}

const context = vm.createContext({
  Blob,
  URL,
  URLSearchParams,
  console,
  document: {
    body: fakeNode(),
    createElement: fakeNode,
    createElementNS: fakeNode,
    querySelector: fakeNode,
    querySelectorAll: () => [],
  },
  fetch: () => new Promise(() => {}),
  localStorage: { getItem: () => null, setItem() {} },
  navigator: {},
  performance,
  setInterval() {},
  setTimeout,
  window: {
    addEventListener() {},
    matchMedia: () => ({ matches: true }),
    requestAnimationFrame() {},
  },
});

const source = fs.readFileSync(new URL("../assets/app.js", import.meta.url), "utf8");
vm.runInContext(source, context);

const payload = {
  timeframes: [{
    key: "1d",
    daily_line_reclaims: {
      signals: [
        {
          symbol: "AAA",
          exchange: "NASDAQ",
          market: "美股",
          opening_reclaim_lines: ["白線"],
          first_reclaim_lines: [],
          is_current_period_bar: true,
          is_live_session: true,
        },
        {
          symbol: "AAA",
          exchange: "NASDAQ",
          market: "美股",
          opening_reclaim_lines: [],
          first_reclaim_lines: ["白線"],
          first_reclaim_confirmed: true,
        },
        {
          symbol: "BBB",
          exchange: "NYSE",
          market: "美股",
          opening_reclaim_lines: [],
          first_reclaim_lines: ["橙線"],
          first_reclaim_confirmed: true,
        },
        {
          symbol: "OLD",
          exchange: "NYSE",
          market: "美股",
          opening_reclaim_lines: ["白線"],
          first_reclaim_lines: [],
          is_current_period_bar: false,
          is_live_session: false,
        },
      ],
    },
    big_black_body_breaks: {
      signals: [
        {
          symbol: "AAA",
          exchange: "NASDAQ",
          market: "美股",
          bars_ago: 0,
          body_drop_pct: 6.2,
        },
        {
          symbol: "2330",
          exchange: "TWSE",
          market: "台股",
          bars_ago: 2,
          body_drop_pct: 5.4,
        },
      ],
    },
  }],
  weekly_reclaim: {
    line_reclaims: {
      signals: [{
        symbol: "2330",
        exchange: "TWSE",
        market: "台股",
        opening_reclaim_lines: [],
        first_reclaim_lines: ["橙線"],
        first_reclaim_confirmed: true,
      }],
    },
    big_black_body_breaks: {
      signals: [{
        symbol: "MSFT",
        exchange: "NASDAQ",
        market: "美股",
        bars_ago: 1,
        body_drop_pct: 5.8,
      }],
    },
  },
};

context.testPayload = payload;

const allDaily = vm.runInContext(
  'exportableLineReclaims(testPayload, "1d").map(tradingViewImportSymbol)',
  context,
);
assert.deepEqual([...allDaily], ["NASDAQ:AAA", "NYSE:BBB"]);

const allWeekly = vm.runInContext(
  'exportableLineReclaims(testPayload, "1w").map(tradingViewImportSymbol)',
  context,
);
assert.deepEqual([...allWeekly], ["TWSE:2330"]);

vm.runInContext('lineReclaimFilterState.line = "橙線"', context);
const orangeDaily = vm.runInContext(
  'exportableLineReclaims(testPayload, "1d").map(tradingViewImportSymbol)',
  context,
);
assert.deepEqual([...orangeDaily], ["NYSE:BBB"]);

vm.runInContext('lineReclaimFilterState.market = "taiwan"', context);
const taiwanDaily = vm.runInContext(
  'exportableLineReclaims(testPayload, "1d").map(tradingViewImportSymbol)',
  context,
);
assert.deepEqual([...taiwanDaily], []);

const taiwanWeekly = vm.runInContext(
  'exportableLineReclaims(testPayload, "1w").map(tradingViewImportSymbol)',
  context,
);
assert.deepEqual([...taiwanWeekly], ["TWSE:2330"]);

vm.runInContext('bigBlackFilterState.market = "all"', context);
const allDailyBigBlack = vm.runInContext(
  'exportableBigBlackSignals(testPayload, "1d").map(tradingViewImportSymbol)',
  context,
);
assert.deepEqual([...allDailyBigBlack], ["TWSE:2330", "NASDAQ:AAA"]);

const allWeeklyBigBlack = vm.runInContext(
  'exportableBigBlackSignals(testPayload, "1w").map(tradingViewImportSymbol)',
  context,
);
assert.deepEqual([...allWeeklyBigBlack], ["NASDAQ:MSFT"]);

vm.runInContext('bigBlackFilterState.market = "us"', context);
const usDailyBigBlack = vm.runInContext(
  'exportableBigBlackSignals(testPayload, "1d").map(tradingViewImportSymbol)',
  context,
);
assert.deepEqual([...usDailyBigBlack], ["NASDAQ:AAA"]);

context.testCardSignal = {
  symbol: "2330",
  exchange: "TWSE",
  market: "台股",
  timeframe_key: "1d",
  bar_time_et: "2026-08-31 日線",
  first_reclaim_lines: ["白線"],
  broken_lines: ["白線"],
  first_reclaim_confirmed: true,
  first_shown_at_utc: "2026-09-01T17:54:56Z",
};
const card = vm.runInContext(
  'makeLineReclaimCard(testCardSignal, "first")',
  context,
);
function cardText(node) {
  if (!node || typeof node !== "object") return "";
  return [node.textContent, ...(node.children || []).map(cardText)].filter(Boolean).join(" ");
}
assert.match(cardText(card), /訊號 K：2026-08-31 日線/);
assert.match(cardText(card), /首次顯示：2026\/09\/02\s+01:54:56/);

context.testBigBlackCardSignal = {
  symbol: "AAA",
  exchange: "NASDAQ",
  market: "美股",
  timeframe_key: "1d",
  bar_time_et: "2026-09-02 日線",
  bars_ago: 0,
  open_price: 106,
  high_price: 106.2,
  low_price: 99.95,
  close_price: 100,
  white_line: 103,
  body_drop_pct: 5.6604,
  lower_wick_range_pct: 0.8,
  body_range_pct: 96,
  first_shown_at_utc: "2026-09-03T01:02:03Z",
};
const bigBlackCard = vm.runInContext(
  'makeBigBlackCard(testBigBlackCardSignal)',
  context,
);
assert.match(cardText(bigBlackCard), /大黑 K/);
assert.match(cardText(bigBlackCard), /實體跌破白線/);
assert.match(cardText(bigBlackCard), /實體跌幅 -5\.66%/);
assert.match(cardText(bigBlackCard), /首次顯示：2026\/09\/03\s+09:02:03/);

console.log("line reclaim export tests passed");
