# KJ Radar System

GitHub Pages 上的多市場 TD Sequential 監測頁面。

## 保留的首頁模組

- 全球期貨脈搏與可嵌入的 TradingView 即時行情帶
- 美股 400 檔、台股、幣安現貨與 Pepperstone 外匯 25 組的 TD Sequential 9／13 清單
- 做多：趨勢帶下方死亡交叉後站回白線

爆量急跌、台灣加權一小時技術圖、指標股盤前／夜盤異動介面與其 Actions 執行步驟均已移除。

## TD 字卡

- 預設只顯示買方標的；賣方可由「方向」選單切換。TD 訊號產生後保留 8 根完成 K 棒，第 8 根仍會顯示。
- 每張字卡有最近 30 根完成 K 棒走勢，`TD 9` 或 `TD 13` 會標在發生的位置。
- 顯示 TD K 棒位於趨勢帶上方、帶內或下方。
- 顯示 TD 當週首個可交易 K 棒的開盤價，是否高於 AI Momentum 白線。
- 台股優先以主力產品題材分類，例如 CPO／矽光子、ABF 載板、高階 PCB、AI 伺服器 ODM；未涵蓋於靜態產品庫的訊號標的，會讀取公開公司業務描述再以產品關鍵字分類。無法驗證時才退回交易所產業分類，不使用「待建檔」文字。
- Pepperstone 外匯池為 25 組主要／次要貨幣對，優先選用低點差、高流動性組合；K 線使用 Yahoo Finance 公開歷史資料，TradingView 連結與匯出使用 `PEPPERSTONE:貨幣對`。
- 資料載入時會顯示同步百分比動畫；完成後顯示最後資料更新時間。

## TradingView 匯入清單

首頁的「下載 TradingView 上傳清單 .TXT」會依目前市場輸出做多 TD 標的：每行一個 `交易所:代號`，重複標的自動合併；順序為市場、主力產品／產業、代號。為了確保可直接匯入 TradingView，不在 TXT 插入產業標題列。

每次 GitHub Actions 完成掃描，亦會產生 `data/KJ-Radar-TradingView.TXT`，內容僅含做多 TD 標的，並依市場與主力產品／產業排序。

## 更新與資料來源

GitHub Actions 平日每 30 分鐘更新一次。行情資料主要來自 Yahoo Finance（透過 `yfinance`）、台灣證交所／櫃買中心公開公司基本資料、台灣期交所標的清單，以及 Binance 公開 K 線與成交資料。Pepperstone 分類依其公開低點差外匯交易對資訊建置。

資料只供研究與監測，不構成投資建議或買賣訊號。
