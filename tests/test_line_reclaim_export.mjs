import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

function fakeNode() {
  return {
    addEventListener() {},
    append() {},
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

console.log("line reclaim export tests passed");
