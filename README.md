# 美股急跌雷達：GitHub Pages 版

這個專案是手機友善的靜態網頁應用程式。GitHub Actions 每 5 分鐘執行一次掃描；GitHub Pages 發布最新結果。每張警示卡都能直接打開對應的 TradingView 圖表。

## 監控條件

警示必須同時符合：

| 條件 | 預設值 |
| --- | ---: |
| 30 分鐘價格變動 | ≤ -3% |
| 最新 5 分鐘成交量 | ≥ 前 20 根 5 分鐘量中位數的 3 倍 |
| 最低價格 | USD 5 |
| 近 4 日平均日成交額 | USD 20M |
| 最新 5 分鐘成交額 | USD 250k |

程式只在美東平日 09:30–16:00 嘗試抓取盤中資料；一般盤外會更新成「一般盤外」狀態。

## 部署到 GitHub Pages

1. 在 GitHub 建立新的儲存庫，例如 us-selloff-radar。
2. 將本資料夾內的所有檔案推送到儲存庫的 main 分支。
3. 到 GitHub 的 Settings → Pages，將 Source 設為 GitHub Actions。
4. 到 Actions，手動執行一次「Scan US selloffs and deploy」。
5. 完成後，手機瀏覽網址：https://你的帳號.github.io/us-selloff-radar/

GitHub Pages 專案是公開網站。不要放入帳密、私有 webhook、券商憑證或任何敏感資料。

## 手機 TradingView 連結

網頁使用 TradingView 的 chart 網址與交易所代號，例如：

~~~text
https://www.tradingview.com/chart/?symbol=NASDAQ%3AAAPL
~~~

在有安裝 TradingView 的手機上，作業系統或 TradingView 可能接管此通用連結並開啟 App；若未接管，連結會安全地以網頁版圖表作為後備。不要使用未被 TradingView 文件保證的私有 URL scheme。

## 調整監控範圍

- 編輯 symbols.csv 的 symbol、exchange 欄位即可增減標的；exchange 應使用 TradingView 慣例，例如 NASDAQ、NYSE、AMEX。
- 要改門檻，可直接修改 scanner.py 中 Settings 的預設值；若日後改接付費資料供應商，請把 API 金鑰存成 GitHub Actions Secrets，不能放進程式碼或網頁。
- 預設清單是高流動性樣本。免費資料不應拿來每 5 分鐘掃描全美市場。

## 重要限制

- GitHub Actions 排程最短為 5 分鐘，且執行可能延遲；它不等同即時行情服務。
- 公開儲存庫若 60 天沒有活動，GitHub 可能自動停用排程。需要定期確認 Actions 的成功執行紀錄。
- Yahoo Finance 與 yfinance 僅供研究與監控；資料可能延遲、缺漏或受限流影響。
- 本專案不會自動下單。警示不是投資建議，需另外核實公司消息、交易暫停、公司行動與市場整體行情。
