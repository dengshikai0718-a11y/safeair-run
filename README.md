# SafeAir Run｜慢跑場域環境查詢

純前端、單一檔案（`index.html`）的響應式網頁原型。依 PM2.5、降雨機率、紫外線指數、體感溫度，以三級燈號判斷台北跑點是否適合出發。

- 唯一外部依賴：Leaflet 1.9.4（unpkg CDN）
- 圖資：© OpenStreetMap 貢獻者、© CARTO
- 資料來源：LASS 空氣盒子（PM2.5）、Open-Meteo（氣象）；無法取得時自動切換為內建 Mock 數據

## 快速預覽

直接在電腦上雙擊 `index.html`（`file://`）即可預覽完整 UI，並以 Mock 數據操作。

> `file://` 環境下，瀏覽器可能不提供定位與 Web Notification。要測試這兩項，請用下方本機伺服器或 GitHub Pages（HTTPS）。

## 本機伺服器

在專案資料夾執行以下任一指令，再用瀏覽器開啟終端機顯示的網址。

使用 Node.js（`npx serve`，預設 http://localhost:3000）：

```bash
npx serve .
```

使用 Python 3（預設 http://localhost:8000）：

```bash
python -m http.server 8000
```

> `localhost` 被瀏覽器視為安全來源，可在電腦上測試定位與通知。手機透過區網 IP（http://192.168.x.x）連線則**不是**安全來源，定位與通知會被封鎖，請改用 GitHub Pages。

## GitHub Pages 零成本部署（手機實機 HTTPS 測試）

1. 將專案推上 GitHub（`index.html` 需位於 repo 根目錄）。
2. 進入 repo 的 **Settings → Pages**。
3. **Build and deployment → Source** 選 **Deploy from a branch**。
4. **Branch** 選 `main`、資料夾選 `/ (root)`，按 **Save**。
5. 約 1～2 分鐘後，頁面上方會顯示網址：`https://<帳號>.github.io/<repo 名稱>/`。
6. 用手機瀏覽器開啟該網址：
   - 允許「位置」權限 → 測試真實定位與「目前位置」環境狀態。
   - 開啟「背景監測」並允許通知 → 測試 Web Notification。
   - iPhone（iOS 16.4 以上）的 Safari 只允許「已加入主畫面」的網頁發送通知：請先點 **分享 → 加入主畫面**，再從主畫面圖示開啟。

之後每次 `git push` 到 `main`，GitHub Pages 會自動重新部署。

## CARTO 底圖金鑰（部署後務必設定）

CARTO 底圖已改為需要（免費）API 金鑰，未帶金鑰時會顯示「API KEY REQUIRED」浮水印圖磚。金鑰設定在 `index.html` 的 `CONFIG.CARTO_API_KEY`，底圖與標籤圖層網址都會自動加上 `?key=`。

由於這是純前端網頁，**金鑰會隨程式碼公開**（repo 與 GitHub Pages 皆可看到）。部署到 GitHub Pages 後，請立即：

1. 登入 CARTO 後台，找到此 API 金鑰的設定。
2. 加入 Referer（允許網域）限制：`https://<帳號>.github.io/*`。
3. 若仍需在本機開發，可一併加入 `http://localhost:*`。注意：`file://` 雙擊開啟時瀏覽器不送 Referer，加上限制後本機雙擊可能無法載入底圖，請改用本機伺服器。
4. 若金鑰疑似被濫用，可在後台重新產生金鑰並更新 `CONFIG.CARTO_API_KEY`。

## 資料模式與 Demo 網址

側邊欄底部可切換「即時資料 / 正常 / 高空汙 / 大雨曝曬」。也可用網址參數直接以情境開啟（不發出任何資料請求）：

```
index.html?mode=normal      # 正常：青年公園 🔴、大佳河濱公園 🟡、其餘 🟢
index.html?mode=pollution   # 高空汙：大佳河濱公園 🟡、其餘 PM2.5 ≥ 35.5 🔴
index.html?mode=storm       # 大雨曝曬：大佳、花博降雨 > 60%，其餘 UVI ≥ 8
```

## PM2.5 熱力圖

地圖右上角（窄螢幕在搜尋列下方右側）的圖層按鈕可開關 PM2.5 熱力圖，開啟時顯示圖例。

- 以測站做 IDW（反距離加權，p = 2）估算 300 m 網格；3 km 內無測站的格點留白。
- 雙線性內插平滑後，依 PM2.5 門檻（≤ 15.4 綠、< 35.5 黃、≥ 35.5 紅）離散上色，再以內嵌的台北市外框多邊形裁切，用 `L.imageOverlay`（透明度 0.5）疊在地圖上。
- 只在資料更新時重算（約 30–70 ms），開關只切換圖層顯示。
- 市外框為手繪簡化多邊形（誤差約數百公尺），僅用於裁切與「全市平均」只計入市內測站，不可當作行政區界線。
- 熱力圖只反映 PM2.5；實際判定仍以跑點的四項指標燈號為準。

## 資料清洗規則（PM2.5 測站）

1. 只保留台北市範圍框內的測站（經度 121.45–121.67、緯度 24.96–25.21）。
2. 排除 PM2.5 **≤ 0** 或 **> 500** μg/m³ 的測站（LASS 實測約半數測站回報 0，多為感測異常，會嚴重拉低 IDW 估算）。
3. 排除更新時間距今超過 60 分鐘的測站。
4. 有效測站 < 2 站或請求失敗（逾時 8 秒）時，自動改用內建 Mock 數據，並顯示「離線 / 展示模式」；滑鼠移到標記上或點擊可看原因。

檢查資料來源欄位（不會印出完整 JSON）：

```bash
python3 tools/pm25_summary.py https://pm25.lass-net.org/data/last-all-airbox.json
```

## Console 已知錯誤（僅「即時資料」模式）

三種 Mock 情境下 Console 應為零錯誤、零警告。「即時資料」模式下可能出現以下兩類錯誤，它們由瀏覽器網路層直接輸出，網頁程式無法攔截；程式已自動降級為展示數據，不影響操作：

| 錯誤訊息 | 來源 | 原因 |
| :--- | :--- | :--- |
| `Access to fetch at 'https://pm25.lass-net.org/...' has been blocked by CORS policy`、`net::ERR_FAILED` | LASS 空氣盒子 | 伺服器回應未帶 `Access-Control-Allow-Origin` 標頭，瀏覽器禁止網頁讀取（另：資料自 2026-09-01 起停止更新） |
| `429 (Too Many Requests)` | Open-Meteo | 同一對外 IP 請求過多被限流（雲端主機、共用網路較常見，通常稍後即恢復） |

## 判定測試

在瀏覽器 Console 執行：

```js
SafeAir.runTests()
```

會測試四項指標的門檻邊界值（15.4 / 15.5 / 35.5、30 / 31 / 60 / 61、5.0 / 8.0、5 / 10 / 30 / 33）、總體判定、缺值處理、主因優先順序，以及狀態文字色的 WCAG AA 對比度，並回報通過數。也可單獨呼叫：

```js
SafeAir.evaluate({ pm25: 12, rain: 40, uvi: 9, feels: 25 })
```

## 專案結構

```
index.html   # 全部 HTML / CSS / JavaScript（內嵌，依功能分段註解）
README.md    # 本文件
tools/pm25_summary.py  # PM2.5 資料來源欄位摘要腳本
```
