# doc-cleaner 整批轉換優化實施計劃 (Batch Conversion Optimization Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為 doc-cleaner 建立統一的多執行緒批次轉換引擎，支援並發加速、即時回調、中途取消與增量跳過，並重構收斂 CLI 與 GUI 的重複批次邏輯。

**Architecture:** 在 `core.py` 中擴充 `convert_files` 作為單一真理來源（Single Source of Truth），利用 `concurrent.futures.ThreadPoolExecutor` 進行並行處理，透過 Thread-local 日誌處理器隔離單檔錯誤訊息，提供 `on_item_done`、`on_progress` 與 `cancel_event`，保證結果列表嚴格保留原始輸入順序；最後讓 CLI 與 GUI 全面重用此引擎。

**Tech Stack:** Python 3.9+, `concurrent.futures.ThreadPoolExecutor`, `threading`, `logging`, `pytest`

**Spec:** [docs/superpowers/specs/2026-10-19-batch-conversion-optimization-design.md](file:///d:/doc-cleaner/docs/superpowers/specs/2026-10-19-batch-conversion-optimization-design.md)

## Global Constraints

- 必須維持與現有 `convert_files` 返回格式 `{file, input, output, status, error}` 100% 向後相容。
- 批次回傳之 `results` 串列順序必須與傳入的 `paths` 順序嚴格一致。
- 必須支援 Python 3.9+，不引入額外外部第三方並發庫（僅使用標準庫）。
- 測試命令格式一律使用：`.\venv\Scripts\python -m pytest <test_path> -v`。

---

### Task 1: 實作 Thread-safe ErrorCapture 與智慧並發計算

**Files:**
- Modify: `core.py:16-26`
- Create: `tests/test_core_batch.py`

**Interfaces:**
- Consumes: `logging.Handler`, `threading.local`
- Produces:
  - `_ThreadSafeErrorCapture(logging.Handler)`
  - `_calculate_concurrency(ai: str, user_concurrency: int = None, config: dict = None) -> int`

- [ ] **Step 1: 編寫失敗的測試**

在 `tests/test_core_batch.py` 建立測試：

```python
import logging
import threading
import pytest
from core import _ThreadSafeErrorCapture, _calculate_concurrency

def test_calculate_concurrency_modes():
    # 顯式指定優先
    assert _calculate_concurrency("gemini", user_concurrency=5) == 5
    assert _calculate_concurrency("none", user_concurrency=2) == 2

    # config 設定優先於自動
    cfg = {"batch": {"concurrency": 6}}
    assert _calculate_concurrency("gemini", config=cfg) == 6

    # 自動計算：none 模式 (大於等於 1 且小於等於 8)
    c_none = _calculate_concurrency("none")
    assert 1 <= c_none <= 8

    # 自動計算：本地模型為 1
    assert _calculate_concurrency("ollama") == 1
    assert _calculate_concurrency("mlx") == 1

    # 自動計算：雲端 API 為 3
    assert _calculate_concurrency("gemini") == 3
    assert _calculate_concurrency("openai") == 3

def test_thread_safe_error_capture_isolation():
    handler = _ThreadSafeErrorCapture()
    logger = logging.getLogger("test_thread_safe_logger")
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)

    results = {}

    def worker(name, message):
        handler.set_thread_target()
        logger.warning(message)
        results[name] = handler.get_messages()

    t1 = threading.Thread(target=worker, args=("t1", "msg_1"))
    t2 = threading.Thread(target=worker, args=("t2", "msg_2"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    logger.removeHandler(handler)
    assert results["t1"] == ["msg_1"]
    assert results["t2"] == ["msg_2"]
```

- [ ] **Step 2: 執行測試並驗證失敗**

執行：`.\venv\Scripts\python -m pytest tests/test_core_batch.py -v`
預期：FAIL（`ImportError: cannot import name '_ThreadSafeErrorCapture'`）

- [ ] **Step 3: 在 `core.py` 實作程式碼**

修改 `core.py`：
替換 `_ErrorCapture` 為 `_ThreadSafeErrorCapture`，並實作 `_calculate_concurrency`：

```python
class _ThreadSafeErrorCapture(logging.Handler):
    """Captures warning-and-above messages per-thread using threading.local."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self._local = threading.local()

    def set_thread_target(self):
        self._local.messages = []

    def get_messages(self):
        return getattr(self._local, "messages", [])

    def emit(self, record):
        messages = getattr(self._local, "messages", None)
        if messages is not None:
            messages.append(record.getMessage())


def _calculate_concurrency(ai="none", user_concurrency=None, config=None):
    """Calculate effective concurrency based on user input, config, or AI mode."""
    if user_concurrency is not None and isinstance(user_concurrency, int) and user_concurrency > 0:
        return user_concurrency

    cfg_concurrency = (config or {}).get("batch", {}).get("concurrency")
    if cfg_concurrency and isinstance(cfg_concurrency, int) and cfg_concurrency > 0:
        return cfg_concurrency

    ai_mode = (ai or "none").lower()
    if ai_mode == "none":
        import os
        return min(8, os.cpu_count() or 4)
    elif ai_mode in ("ollama", "mlx"):
        return 1
    else:
        return 3
```

- [ ] **Step 4: 執行測試並驗證通過**

執行：`.\venv\Scripts\python -m pytest tests/test_core_batch.py -v`
預期：PASS

- [ ] **Step 5: 提交程式碼**

```bash
git add core.py tests/test_core_batch.py
git commit -m "feat(core): add ThreadSafeErrorCapture and concurrency calculation"
```

---

### Task 2: 實作增量轉換與目標路徑檢查機制

**Files:**
- Modify: `core.py`
- Modify: `tests/test_core_batch.py`

**Interfaces:**
- Consumes: `Path`, `os.path`
- Produces:
  - `_resolve_target_output_path(input_path: str, output_dir: str, output_format: str) -> str`
  - `_check_skip_existing(input_path: str, output_path: str) -> bool`

- [ ] **Step 1: 編寫失敗的測試**

在 `tests/test_core_batch.py` 新增：

```python
import os
import time
from pathlib import Path
from core import _resolve_target_output_path, _check_skip_existing

def test_resolve_target_output_path(tmp_path):
    src = str(tmp_path / "document.pdf")
    out_dir = str(tmp_path / "out")
    
    assert _resolve_target_output_path(src, out_dir, "md") == str(tmp_path / "out" / "document.md")
    assert _resolve_target_output_path(src, out_dir, "epub") == str(tmp_path / "out" / "document.epub")
    assert _resolve_target_output_path(src, out_dir, "both") == str(tmp_path / "out" / "document.md")

def test_check_skip_existing(tmp_path):
    src = tmp_path / "doc.txt"
    out = tmp_path / "doc.md"
    src.write_text("hello", encoding="utf-8")
    
    # 輸出檔不存在 -> 不跳過
    assert not _check_skip_existing(str(src), str(out))
    
    # 輸出檔舊於來源 -> 不跳過
    time.sleep(0.05)
    src.write_text("updated", encoding="utf-8")
    out.write_text("old", encoding="utf-8")
    os.utime(str(out), (time.time() - 10, time.time() - 10))
    assert not _check_skip_existing(str(src), str(out))
    
    # 輸出檔新於來源 -> 跳過
    os.utime(str(out), (time.time() + 10, time.time() + 10))
    assert _check_skip_existing(str(src), str(out))
```

- [ ] **Step 2: 執行測試並驗證失敗**

執行：`.\venv\Scripts\python -m pytest tests/test_core_batch.py -k "resolve_target_output_path or check_skip_existing" -v`
預期：FAIL（`ImportError: cannot import name '_resolve_target_output_path'`）

- [ ] **Step 3: 在 `core.py` 實作增量輔助函式**

在 `core.py` 實作：

```python
def _resolve_target_output_path(filepath, output_dir, output_format="md"):
    """Compute primary target output path for a given input file."""
    from parsers.x_article import is_x_article_url, extract_article_id
    if is_x_article_url(filepath):
        art_id = extract_article_id(filepath)
        stem = f"x_article_{art_id}"
    else:
        stem = Path(filepath).stem

    ext = ".md" if output_format in ("md", "both") else ".epub"
    return str(Path(output_dir) / f"{stem}{ext}")


def _check_skip_existing(input_path, output_path):
    """Return True if output_path exists and is newer than or equal to input_path."""
    try:
        if not os.path.exists(output_path):
            return False
        # URLs don't have local mtime, never skip by mtime
        if input_path.startswith("http://") or input_path.startswith("https://"):
            return False
        return os.path.getmtime(output_path) >= os.path.getmtime(input_path)
    except OSError:
        return False
```

- [ ] **Step 4: 執行測試並驗證通過**

執行：`.\venv\Scripts\python -m pytest tests/test_core_batch.py -v`
預期：PASS

- [ ] **Step 5: 提交程式碼**

```bash
git add core.py tests/test_core_batch.py
git commit -m "feat(core): add target output resolution and skip_existing check"
```

---

### Task 3: 重構 `core.convert_files` 支援多執行緒並發、回調與取消

**Files:**
- Modify: `core.py:52-140`
- Modify: `tests/test_core_batch.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `ThreadPoolExecutor`, `_ThreadSafeErrorCapture`, `_calculate_concurrency`, `_check_skip_existing`
- Produces:
  - `convert_files(paths, output_resolver=None, ai="none", output_format="md", config=None, config_path=None, dry_run=False, prompt_name=None, concurrency=None, on_item_done=None, on_progress=None, cancel_event=None, skip_existing=False) -> list[dict]`

- [ ] **Step 1: 編寫失敗的測試**

在 `tests/test_core_batch.py` 新增並發、回調、取消與排序測試：

```python
def test_convert_files_concurrent_order_and_callbacks(tmp_path):
    from core import convert_files
    
    docs = []
    for i in range(5):
        f = tmp_path / f"doc_{i}.txt"
        f.write_text(f"content {i}", encoding="utf-8")
        docs.append(str(f))

    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir, exist_ok=True)

    progress_calls = []
    done_items = []

    def on_prog(completed, total):
        progress_calls.append((completed, total))

    def on_item(result, completed, total):
        done_items.append(result["file"])

    results = convert_files(
        docs,
        output_resolver=lambda _: out_dir,
        ai="none",
        concurrency=3,
        on_progress=on_prog,
        on_item_done=on_item,
    )

    # 1. 結果順序必須與輸入順序完全一致
    assert [r["file"] for r in results] == [f"doc_{i}.txt" for i in range(5)]
    assert all(r["status"] == "ok" for r in results)

    # 2. 進度回調次數與總數必須正確
    assert len(progress_calls) == 5
    assert len(done_items) == 5
    assert progress_calls[-1] == (5, 5)

def test_convert_files_cancellation(tmp_path):
    from core import convert_files
    
    docs = []
    for i in range(6):
        f = tmp_path / f"cancel_doc_{i}.txt"
        f.write_text(f"data {i}", encoding="utf-8")
        docs.append(str(f))

    out_dir = str(tmp_path / "out")
    cancel_evt = threading.Event()

    def on_item(result, completed, total):
        if completed == 2:
            cancel_evt.set()

    results = convert_files(
        docs,
        output_resolver=lambda _: out_dir,
        ai="none",
        concurrency=1,
        cancel_event=cancel_evt,
        on_item_done=on_item,
    )

    # 驗證未執行的檔案被標記或提早中斷
    statuses = [r["status"] for r in results]
    assert "cancelled" in statuses or len(statuses) < len(docs) or statuses.count("ok") < 6
```

- [ ] **Step 2: 執行測試並驗證失敗**

執行：`.\venv\Scripts\python -m pytest tests/test_core_batch.py -k "concurrent_order or cancellation" -v`
預期：FAIL（因現有 `convert_files` 尚不支援 `concurrency` 等新參數）

- [ ] **Step 3: 重構 `core.py` 實作執行緒池與生命週期**

在 `core.py` 中：
1. 重構 `_run_one`，使用全域單例 `_GLOBAL_CAPTURE = _ThreadSafeErrorCapture()`，在進入時呼叫 `_GLOBAL_CAPTURE.set_thread_target()`，結束時取出 messages。
2. 重構 `convert_files`：
   - 建立 `ThreadPoolExecutor(max_workers=eff_concurrency)`。
   - 支援 `cancel_event`。
   - 支援 `skip_existing`。
   - 呼叫 `on_progress(completed, total)` 與 `on_item_done(result, completed, total)`。
   - 嚴格維持輸入索引順序。

```python
_GLOBAL_CAPTURE = _ThreadSafeErrorCapture()
_CAPTURE_INITIALIZED = False

def _ensure_capture_registered():
    global _CAPTURE_INITIALIZED
    if not _CAPTURE_INITIALIZED:
        for _log in (logging.getLogger("doc-cleaner"), logging.getLogger("parsers"), logging.getLogger("classifiers")):
            _log.addHandler(_GLOBAL_CAPTURE)
        _CAPTURE_INITIALIZED = True

def _run_one(filepath, ai_backend, prompt, config, output_dir, output_format="md", dry_run=False, skip_existing=False):
    _ensure_capture_registered()
    _GLOBAL_CAPTURE.set_thread_target()

    # 增量跳過檢查
    if skip_existing and not dry_run:
        target_out = _resolve_target_output_path(filepath, output_dir, output_format)
        if _check_skip_existing(filepath, target_out):
            return {
                "file": Path(filepath).name,
                "input": str(Path(filepath).resolve()),
                "output": str(Path(target_out).resolve()),
                "status": "skipped",
                "error": "已存在最新輸出檔，跳過",
            }

    status_raw, out_path = process_file(
        filepath, ai_backend, prompt, config, output_dir, output_format=output_format, dry_run=dry_run
    )
    captured = _GLOBAL_CAPTURE.get_messages()

    status = _STATUS_MAP.get(status_raw, "error")
    if status == "error":
        error_msg = captured[-1] if captured else "轉換失敗"
    elif status == "skipped":
        if any("export" in m.lower() or "匯出" in m for m in captured):
            error_msg = "此檔無可擷取的內嵌內容；請用原 App 匯出 PDF 後再轉換"
        else:
            error_msg = "未擷取到文字內容"
    else:
        error_msg = None

    return {
        "file": Path(filepath).name,
        "input": str(Path(filepath).resolve()),
        "output": str(Path(out_path).resolve()) if out_path else None,
        "status": status,
        "error": error_msg,
    }

def convert_files(
    paths,
    output_resolver=None,
    ai="none",
    output_format="md",
    config=None,
    config_path=None,
    dry_run=False,
    prompt_name=None,
    concurrency=None,
    on_item_done=None,
    on_progress=None,
    cancel_event=None,
    skip_existing=False,
):
    if config is None:
        config, ai_backend, prompt = _build_env(ai=ai, config_path=config_path, prompt_name=prompt_name)
    else:
        ai_backend = create_ai_backend(ai, config)
        prompt = load_prompt(config, config_path=config_path, prompt_name=prompt_name) if ai_backend else None

    paths_list = [str(Path(p).resolve()) if not (isinstance(p, str) and (p.startswith("http://") or p.startswith("https://"))) else p for p in paths]
    total = len(paths_list)
    results = [None] * total
    if total == 0:
        return []

    eff_concurrency = _calculate_concurrency(ai=ai, user_concurrency=concurrency, config=config)
    completed_count = 0
    lock = threading.Lock()

    from concurrent.futures import ThreadPoolExecutor

    def _worker(idx, p):
        nonlocal completed_count
        if cancel_event and cancel_event.is_set():
            res = {
                "file": Path(p).name,
                "input": p,
                "output": None,
                "status": "cancelled",
                "error": "使用者取消",
            }
        else:
            out_dir = output_resolver(p) if output_resolver else str(Path(p).parent)
            res = _run_one(
                p, ai_backend, prompt, config, out_dir,
                output_format=output_format, dry_run=dry_run, skip_existing=skip_existing
            )

        with lock:
            results[idx] = res
            completed_count += 1
            cur_done = completed_count

        if on_progress:
            try:
                on_progress(cur_done, total)
            except Exception:
                pass
        if on_item_done:
            try:
                on_item_done(res, cur_done, total)
            except Exception:
                pass
        return res

    with ThreadPoolExecutor(max_workers=eff_concurrency) as executor:
        futures = [executor.submit(_worker, i, path) for i, path in enumerate(paths_list)]
        for f in futures:
            f.result()

    return results
```

- [ ] **Step 4: 執行單元與既有測試**

執行：
```powershell
.\venv\Scripts\python -m pytest tests/test_core.py -v
.\venv\Scripts\python -m pytest tests/test_core_batch.py -v
```
預期：全部 PASS

- [ ] **Step 5: 提交程式碼**

```bash
git add core.py tests/test_core_batch.py
git commit -m "refactor(core): implement concurrent convert_files with callbacks, cancel and skip_existing"
```

---

### Task 4: CLI 整合：支援參數與即時終端輸出

**Files:**
- Modify: `cleaner.py:840-950`
- Create: `tests/test_cli_batch.py`

**Interfaces:**
- Consumes: `core.convert_files(concurrency, skip_existing, on_item_done)`
- Produces: CLI `--concurrency` / `-j` 與 `--skip-existing` 參數支援

- [ ] **Step 1: 編寫失敗的測試**

在 `tests/test_cli_batch.py` 測試 CLI 參數解析與即時印出：

```python
import sys
import subprocess
from pathlib import Path

def test_cli_arguments_parsing(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("sample content", encoding="utf-8")
    out = tmp_path / "out"
    
    cmd = [
        sys.executable,
        "cleaner.py",
        "-i", str(f),
        "-o", str(out),
        "--ai", "none",
        "-j", "2",
        "--skip-existing",
        "--summary"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).parent.parent))
    assert proc.returncode == 0
    assert "Done: 1/1 files processed." in proc.stderr or "Done: 1/1 files processed." in proc.stdout
```

- [ ] **Step 2: 執行測試並驗證失敗**

執行：`.\venv\Scripts\python -m pytest tests/test_cli_batch.py -v`
預期：FAIL（`unrecognized arguments: -j 2 --skip-existing`）

- [ ] **Step 3: 修改 `cleaner.py` 增加 CLI 參數與即時回調**

在 `cleaner.py` 中：
1. `argparse` 加入：
   ```python
   parser.add_argument("--concurrency", "-j", type=int, default=None, help="maximum concurrent files to process (default: auto)")
   parser.add_argument("--skip-existing", action="store_true", help="skip conversion if output file exists and is newer than source")
   ```
2. 在 `main()` 中定義即時終端回調：
   ```python
   def _cli_on_item(res, done, total):
       st = res["status"]
       filename = res["file"]
       if st in ("ok", "dry_run"):
           logger.info(f"[{done}/{total}] ✓ {filename} → {res.get('output')} ({st})")
       elif st == "skipped":
           logger.info(f"[{done}/{total}] ⏩ {filename} (skipped: {res.get('error')})")
       elif st == "cancelled":
           logger.warning(f"[{done}/{total}] ⏹ {filename} (cancelled)")
       else:
           logger.error(f"[{done}/{total}] ✗ {filename} (error: {res.get('error')})")
   ```
3. 傳入 `core.convert_files(..., concurrency=args.concurrency, skip_existing=args.skip_existing, on_item_done=_cli_on_item)`。

- [ ] **Step 4: 執行測試並驗證通過**

執行：`.\venv\Scripts\python -m pytest tests/test_cli_batch.py -v`
預期：PASS

- [ ] **Step 5: 提交程式碼**

```bash
git add cleaner.py tests/test_cli_batch.py
git commit -m "feat(cli): add -j/--concurrency, --skip-existing and real-time progress logging"
```

---

### Task 5: GUI 整合：重構 `macapp/app.py` 批次轉換工作執行緒

**Files:**
- Modify: `macapp/app.py:280-366`
- Modify: `tests/test_macapp.py`

**Interfaces:**
- Consumes: `core.convert_files`
- Produces: 簡潔的 `Api._convert_batch_worker` 委派實作

- [ ] **Step 1: 檢查並補足 GUI 批次轉換單元測試**

在 `tests/test_macapp.py` 新增 `test_convert_batch_worker_delegates_to_core`。

- [ ] **Step 2: 執行測試確認現有行為**

執行：`.\venv\Scripts\python -m pytest tests/test_macapp.py -v`

- [ ] **Step 3: 重構 `macapp/app.py:Api._convert_batch_worker`**

將原先近 60 行的手動 `for` 迴圈移除，直接呼叫 `core.convert_files`：

```python
    def _convert_batch_worker(self, paths, output_mode="sibling", custom_dir=None, output_format="md"):
        # ... 前置環境設定與 config 解析保持不變 ...
        desktop = str(Path.home() / "Desktop")
        if output_mode == "custom" and not (custom_dir and os.path.isdir(custom_dir)):
            output_mode = "sibling"
            if self._window:
                self._window.evaluate_js("onNotice('fallbackSibling')")

        def _resolver(path):
            if output_mode == "desktop":
                return desktop
            if output_mode == "custom" and custom_dir:
                return custom_dir
            if path.startswith("http://") or path.startswith("https://"):
                return desktop
            return str(Path(path).parent)

        def _on_item(result, completed, total):
            if self._window:
                self._window.evaluate_js(f"onProgress({completed}, {total})")
                self._window.evaluate_js(
                    f"onResult({json.dumps(result, ensure_ascii=False)})"
                )

        _core.convert_files(
            paths,
            output_resolver=_resolver,
            ai=ai_backend_name,
            output_format=output_format,
            config=config,
            prompt_name=prompt_mode,
            cancel_event=self._cancel_event,
            on_item_done=_on_item,
        )

        if self._cancel_event.is_set():
            if self._window:
                self._window.evaluate_js("onCancelled()")
        else:
            if self._window:
                self._window.evaluate_js("onComplete()")
```

- [ ] **Step 4: 執行測試並驗證**

執行：`.\venv\Scripts\python -m pytest tests/test_macapp.py -v`
預期：PASS

- [ ] **Step 5: 提交程式碼**

```bash
git add macapp/app.py tests/test_macapp.py
git commit -m "refactor(gui): delegate batch conversion loop to core.convert_files"
```

---

### Task 6: 系統全流程端到端測試與回歸驗證

**Files:**
- Create: `tests/test_batch_e2e.py`

**Interfaces:**
- 涵蓋所有檔案格式並行、取消中斷、增量跳過與錯誤捕獲完整流程。

- [ ] **Step 1: 編寫端到端 E2E 測試**

測試多格式（txt, docx, jsonl）並發批次、增量跳過與取消情境。

- [ ] **Step 2: 執行全部測試套件**

執行：`.\venv\Scripts\python -m pytest tests/ -v`
預期：全數測試通過。

- [ ] **Step 3: 驗證 CLI 指令實測**

執行：
```powershell
.\venv\Scripts\python cleaner.py -i README.md -o output/ -j 2 --skip-existing --summary
```
驗證輸出 JSON 格式正確，狀態為 `ok` 或 `skipped`。

- [ ] **Step 4: 提交最終程式碼**

```bash
git add tests/test_batch_e2e.py
git commit -m "test: add comprehensive e2e tests for batch conversion optimization"
```
