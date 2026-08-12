# KJ Radar System

GitHub Pages 上的多市場 TD Sequential 監測頁面。

## 保留的首頁模組

- 全球期貨脈搏與可嵌入的 TradingView 即時行情帶
- 台灣加權・1 小時技術圖：K 線、TD 9／13、白線／黃線、EMA 50／100 趨勢帶
- 指標股盤前／夜盤異動
- 美股、台股與幣安現貨的 TD Sequential 9／13 清單
- 做多：趨勢帶下方死亡交叉後站回白線

爆量急跌掃描介面與其 Actions 執行步驟已移除。

## TD 字卡

- 預設只顯示買方標的；賣方可由「方向」選單切換。
- 每張字卡有最近 30 根完成 K 棒走勢，`TD 9` 或 `TD 13` 會標在發生的位置。
- 顯示 TD K 棒位於趨勢帶上方、帶內或下方。
- 顯示 TD 當週首個可交易 K 棒的開盤價，是否高於 AI Momentum 白線。
- 台股優先以主力產品題材分類，例如 CPO／矽光子、ABF 載板、高階 PCB、AI 伺服器 ODM；尚未建檔的代號會明確標示，避免以猜測分類。

## TradingView 匯入清單

首頁的「下載 TradingView 上傳清單 .TXT」會依目前篩選器輸出純文字清單：每行一個 `交易所:代號`，重複標的自動合併。直接在 TradingView 的自選清單匯入 TXT 即可。

每次 GitHub Actions 完成掃描，亦會產生 `data/KJ-Radar-TradingView.TXT`，內容為預設買方 TD 標的。

## 更新與資料來源

GitHub Actions 平日每 30 分鐘更新一次。行情資料主要來自 Yahoo Finance（透過 `yfinance`）、台灣證交所／櫃買中心公開公司基本資料、台灣期交所標的清單，以及 Binance 公開 K 線與成交資料。

資料只供研究與監測，不構成投資建議或買賣訊號。
