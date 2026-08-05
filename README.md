# 美股急跌雷達：GitHub Pages 版

這個專案是手機友善的靜態網頁應用程式。GitHub Actions 每 5 分鐘執行一次掃描；GitHub Pages 發布最新結果。每張警示卡都能直接打開對應的 TradingView 圖表。

除了急跌爆量掃描，首頁也提供 **Sequential 7／8／9／13 多週期監測**，依使用者提供的 quantifytools Pine Script 規則，顯示目前最後一根已完成 K 棒上的訊號：

| 週期 | Yahoo 資料週期 | TradingView 開啟週期 |
| --- | --- | --- |
| 15 分鐘 | 15m | 15 分鐘 |
| 1 小時 | 1h | 60 分鐘 |
| 日線 | 1d | 日線 |

這個模組只顯示 Setup 9 與 Countdown 13，並保留最近 **5 根已完成 K 棒**（含最新一根）內出現的訊號；超過 5 根會自動排除。網站可篩選美股、台股個股期貨標的、幣安現貨、買方、賣方，並在每個週期內依訊號出現時間排序。台股訊號會顯示證券代號與中文名稱，例如 `2330 台積電`。

篩選的預設值放在 `.github/workflows/scan-and-deploy.yml`：`RECENT_SIGNAL_BARS: "5"` 代表保留最近 5 根，`BINANCE_TOP_USDT_PAIRS: "40"` 代表選取前 40 檔；可依需要調整。

### 監控市場與標的範圍

- **美股**：`symbols.csv` 的既有清單。
- **台股個股期貨標的**：每次執行時讀取台灣期貨交易所的股票期貨公開清單，去除同標的小型期貨重複項後，以其上市／上櫃的現貨標的計算。ETF 期貨不列入此區塊。
- **幣安現貨**：每次依 24 小時 USDT 成交額選取前 40 個非穩定幣、非槓桿代幣交易對；可在 GitHub Actions 的環境變數 `BINANCE_TOP_USDT_PAIRS` 調整為 1–100。

幣安與台股的資料也只使用已完成 K 棒。台股收盤時間以台北時間 13:30 為準；幣安日線以 UTC 日界線為準。

## Sequential 計算方式

- **買方 Setup**：收盤價低於 4 根 K 棒前的收盤價，連續計數；第 9 根重新從 1 開始。
- **賣方 Setup**：收盤價高於 4 根 K 棒前的收盤價，連續計數；第 9 根重新從 1 開始。
- Setup 9 啟動對應方向的 Countdown 13。買方條件為收盤低於 2 根前低點；賣方條件為收盤高於 2 根前高點，Countdown 不要求連續。
- 相反方向的 Setup 9、同向的新 Setup 9，或突破／跌破已完成 Setup 的界線時，會依原 Pine Script 的邏輯重設或失效 Countdown。
- 盤中尚未收完的 15 分鐘、1 小時、日線 K 棒不計入，避免網頁數字在該根 K 棒內反覆改變。

本模組是依使用者提供的 **Discreet sequential counts (7, 8, 9, 13)** Pine Script 邏輯重製；原作者為 quantifytools，原始程式碼採 Mozilla Public License 2.0。

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
