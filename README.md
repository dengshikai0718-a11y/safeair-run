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

## 專案結構

```
index.html   # 全部 HTML / CSS / JavaScript（內嵌，依功能分段註解）
README.md    # 本文件
```
