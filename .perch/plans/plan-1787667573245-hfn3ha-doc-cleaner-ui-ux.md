# doc-cleaner 桌面 App UI/UX 重構

## 目標
把 `macapp/app.py` 內嵌的 ~830 行 HTML/CSS/JS 字串抽出來重寫，解決「醜 + 難用」兩個問題，同時保持 Python 橋接介面（`pywebview.api.*`）完全不變，讓 `tests/test_macapp.py` 既有的 505 行測試照常通過。

## 一、結構重構（先做，後面都靠它）
- 新增 `macapp/static/index.html`、`style.css`、`app.js`
- `app.py` 改用 `webview.create_window(url=<static>/index.html)` 載入，刪除 `_HTML` 字串
- 打包免調整：`pyproject.toml` 的 sources 已含整個 `macapp/` 目錄
- 順手修掉內嵌字串的編碼風險（目前檔案裡已有亂碼跡象的 emoji 圖示）

## 二、UX 重構
- **單屏流程**：視窗內不捲動就能完成「加入檔案 → 確認設定 → 轉換」。拖放區升級為主視覺 hero 區塊
- **設定壓縮**：輸出位置與格式改成兩排分段控制項（segmented control），翻譯選項變核取方塊並排
- **X 憑證面板改為情境顯示**：只有當佇列裡出現 X/Twitter 網址時才展開，平時完全隱藏
- **轉換列常駐底部（sticky footer）**：閒置時是「轉換 N 個文件」主按鈕；執行中變身進度條 + 「第 i / n 個：檔名」，並新增**取消**功能（Python 端加 `cancel_batch()`，批次迴圈每個檔案之間檢查旗標——唯一需要動橋接的新方法，採純新增、不改舊簽名）
- **結果總覽**：頂部顯示「✓ 5 成功 · ⚠ 1 跳過 · ✕ 0 失敗」摘要 chips，每列保留預覽／揭示按鈕
- **通知改 toast**：取代所有 `alert()`（儲存憑證、載入上限、輸出資料夾失效等）

## 三、視覺系統
- CSS custom properties 設計代幣（色票、間距、圓角、陰影）集中管理
- 沿用 SF/PingFang 字族，字級階層重整（11/13/15/17/22）
- 統一 SVG 線性圖示取代 emoji（檔案類型、成功/警告/失敗、資料夾）
- 支援 `prefers-color-scheme` 深色模式
- hover / focus-visible / disabled 狀態補齊，焦點可見（鍵盤可用性）

## 四、驗證
- `pytest tests/test_macapp.py tests/test_mdpreview.py tests/test_settings.py` 全綠（橋接不變的證據）
- `python -c "import macapp.app"` 冒煙檢查 + HTML/CSS/JS 語法檢查
- GUI 實機啟動驗證留給使用者（`briefcase run` 或 `python -m macapp`）

## 不做的事
- 不改任何 parser / core 轉換邏輯
- 不引入前端框架或打包工具鏈
- 不更動既有 `Api` 方法的簽名與回傳格式（只新增 `cancel_batch()`）