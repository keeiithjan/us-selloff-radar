# KJ Long Screener 操作 SOP

`KJ_Long_Screener.pine` 是 KJ Radar System 的 TradingView 篩選版，只輸出做多條件：

1. 買方 TD Setup 9／Countdown 13。
2. TD 訊號產生後 8 根完成 K 棒內。
3. 白線／黃線在 EMA 50／100 趨勢帶下方死亡交叉後，收盤站回白線的做多訊號。

## 1. 建立指標

1. 在 TradingView 開啟任意圖表，進入「Pine 編輯器」。
2. 開啟 `KJ_Long_Screener.pine`，複製全部內容並貼上。
3. 按「儲存」後按「新增至圖表」。
4. 將 `KJ Long Screener · TD + Ribbon Reclaim` 加入最愛，Pine Screener 才會列出它。

## 2. 匯入台股篩選母清單

1. 下載網站產生的 `data/KJ-Taiwan-Pine-Screener-Universe.TXT`。
2. TradingView 的「自選清單」選單中建立新清單，例如 `KJ 台股母清單`。
3. 使用匯入功能上傳 TXT。每行皆為 `TWSE:代號` 或 `TPEX:代號`，沒有說明文字，可直接匯入。

這份母清單與「當前做多 TD 訊號 TXT」不同：母清單用來找出未來新訊號；當前訊號 TXT 只方便快速開啟已觸發的標的。

## 3. Pine Screener 篩選設定

每個時間框架分開建立一個儲存的篩選畫面：

| 用途 | 時間框架 | 欄位與條件 |
| --- | --- | --- |
| TD 做多 | 15 分鐘 | `KJ Buy TD Active = 1` |
| TD 做多 | 1 小時 | `KJ Buy TD Active = 1` |
| TD 做多 | 日線 | `KJ Buy TD Active = 1` |
| 趨勢帶回站 | 15 分鐘 | `KJ White Reclaim Active = 1` |
| 趨勢帶回站 | 1 小時 | `KJ White Reclaim Active = 1` |

在每個畫面額外加入並排序：

- `KJ TD Value (9/13)`：13 優先。
- `KJ TD Age (bars)`：由小到大，最新訊號優先。
- `KJ Long Score`：2 為趨勢帶回站，1 為 TD，3 代表兩項條件同時仍在有效期。
- `KJ TD Below Ribbon`：設為 1 時，只保留 TD 發生當下位於趨勢帶下方的標的。

## 4. 手機通知

在自選清單建立 Watchlist Alert，條件選擇 `KJ Long Candidate`，頻率選「每根 K 棒收盤一次」。這樣 TD 與回站只在 K 棒確認後通知，不會收到盤中尚未成立的訊號。

警報由 TradingView 伺服器執行；電腦不必開著，開啟手機 App 的推播權限即可接收通知。

## 限制與一致性

- Pine Screener 一次只使用一個指標，因此 TD 與回站邏輯已合併在這支指標內。
- 15 分鐘、1 小時與日線需分開掃描，避免跨時間框架未收 K 的訊號混用。
- 產業／主力產品分類維持在 KJ Radar 網頁中；TradingView TXT 為純代號格式，以確保匯入成功。
- AI Momentum 使用原指標的 `jdehorty/KernelFunctions/2` 公開函式庫；若 TradingView 顯示函式庫權限問題，請將錯誤訊息傳給我，我會改為內嵌版本。
