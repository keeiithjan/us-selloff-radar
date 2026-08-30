# KJ Radar System

GitHub Pages 上的多市場 TD Sequential 監測頁面。

## 保留的首頁模組

- 首頁最上方的日線白線／橙線站回雷達：前一交易日必須先有黑 K 實體由線上跌到線下；隔日開盤重新站上被跌破的同一條線時列入「隔日開盤立即站回」，盤中符合實體完全站回或紅 K 實體穿回時列入「站回第一根」。白線與橙線各自追蹤，並提供頁面／PWA 開啟期間的瀏覽器通知去重。
- 全球期貨脈搏與可嵌入的 TradingView 即時行情帶
- 美股 500 檔（跨能源、公用事業、工業國防、核能與原物料、潔淨能源、金融科技、跨國消費、汽車運輸、軟體與醫療等類別）、台股、幣安 USDT 永續與 Pepperstone 高流動性 CFD 的 TD Sequential 9／13 清單
- 做多：趨勢帶下方死亡交叉後站回白線
- 週線白線站回：完全對齊 KJ 白線黃線＋1H Screener V12 的週K規則。有效跌破必須整根週K實體都低於 AI Momentum 白線；首根須收盤站回，並僅追蹤後續第 1～3 根且當前週K開盤／收盤均在白線上。第 2 根盤中跌破白線 0.1% 後收回優先最高、第 3 根次之；週K僅要求白線位於黃線上方，不要求近期白金叉。1H 站回第 1～3 根僅作為週K合格後的遞減加分；月線收盤位於 AI 白線上方另加 70 分，兩者都不會混入週K篩選器。
- 可安裝的 PWA App：Android／Chrome／Edge 使用「安裝 App」，iPhone／iPad 於 Safari 選「分享」→「加入主畫面」

爆量急跌、台灣加權一小時技術圖、指標股盤前／夜盤異動介面與其 Actions 執行步驟均已移除。

## TD 字卡

- 預設只顯示買方標的；賣方可由「方向」選單切換。TD 訊號產生後保留 8 根完成 K 棒，第 8 根仍會顯示。
- 每張字卡有最近 30 根完成 K 棒走勢，`TD 9` 或 `TD 13` 會標在發生的位置。
- 顯示 TD K 棒位於趨勢帶上方、帶內或下方。
- 顯示 TD 當週首個可交易 K 棒的開盤價，是否高於 AI Momentum 白線。
- 台股優先以主力產品題材分類，例如 CPO／矽光子、ABF 載板、高階 PCB、AI 伺服器 ODM；未涵蓋於靜態產品庫的訊號標的，會讀取公開公司業務描述再以產品關鍵字分類。無法驗證時才退回交易所產業分類，不使用「待建檔」文字。
- Pepperstone CFD 池只保留高流動性核心商品：黃金、白銀、WTI／布蘭特原油、美日德主要指數與八組核心貨幣對；技術 K 線使用 Yahoo Finance 對應期貨／指數代理資料，TradingView 連結與匯出使用 `PEPPERSTONE:商品代號`。
- 資料載入時會顯示同步百分比動畫；完成後顯示最後資料更新時間。

## TradingView 匯入清單

首頁的「下載 TradingView 上傳清單 .TXT」會依目前市場輸出做多 TD 標的：每行一個 `交易所:代號`，重複標的自動合併；順序為市場、主力產品／產業、代號。為了確保可直接匯入 TradingView，不在 TXT 插入產業標題列。

每次 GitHub Actions 完成掃描，亦會產生 `data/KJ-Radar-TradingView.TXT`，內容僅含做多 TD 標的，並依市場與主力產品／產業排序。

週線監控可由首頁依目前市場直接匯出，Actions 同時寫入 `data/KJ-Radar-Weekly-White-Reclaim.TXT`。每行皆為可直接匯入 TradingView 的 `交易所:代號`，按結構分數、市場、產品／產業排序。

## TradingView Pine Screener

- `tradingview/KJ_Daily_White_Orange_Reclaim.pine`：日線黑 K 實體跌破白線／橙線、隔日開盤重新站上同一條線的 Watchlist Alert，以及跌破後第一根站回訊號。
- `tradingview/KJ_Long_Screener_15m.pine`：固定 15 分鐘掃描。
- `tradingview/KJ_Long_Screener.pine`：固定 1 小時掃描。
- `tradingview/KJ_Long_Screener_1D.pine`：固定日線掃描。
- `data/KJ-Taiwan-Pine-Screener-Universe.TXT`：每次掃描後產生的台股 Pine Screener 母清單；用來發掘未來新訊號，不限於目前已觸發 TD 的標的。
- `data/KJ-Binance-Crypto-Perpetuals.TXT`：Binance 所有交易中 USDⓈ-M 加密 USDT 永續合約，依 Binance Futures 公開 `exchangeInfo` 每次掃描更新。
- `data/KJ-Binance-Stock-Perpetuals.TXT`：Binance TradFi 的個股永續合約清單，僅含個股、排除 ETF／指數／商品。
- `data/KJ-Pepperstone-Liquid-CFDs.TXT`：Radar 同步監測的 18 個高流動性 Pepperstone CFD，無訊號時仍可直接匯入 TradingView。
- 完整操作請見 `tradingview/PINE_SCREENER_SOP.md`。

## 更新與資料來源

GitHub Actions 平日每 30 分鐘更新一次。行情資料主要來自 Yahoo Finance（透過 `yfinance`）、台灣證交所／櫃買中心公開公司基本資料、台灣期交所標的清單，以及 Binance 公開 K 線與成交資料。Pepperstone 商品池依其公開 CFD 商品建置；由於 CFD 沒有集中式成交量，流動性以對應期貨／現貨指數的市場深度作為代理，非 Pepperstone 自身成交量。

GitHub Pages 負責 App 前端與 PWA 離線殼層；GitHub Actions 則是掃描後台，負責更新 `market.json` 與 `sequential.json` 後自動部署。App 每 60 秒重新讀取資料；離線時只顯示上次成功快取的資料。

開盤站回區會在前端取得新一輪 `sequential.json` 後立刻置頂更新；由於 GitHub Pages 是靜態網站，網站資料的新鮮度仍取決於 GitHub Actions 排程。真正逐筆、開盤第一個 tick 的通知仍應以 TradingView Watchlist Alert 為主，網站通知是頁面或 PWA 保持開啟時的補充通道。

資料只供研究與監測，不構成投資建議或買賣訊號。
