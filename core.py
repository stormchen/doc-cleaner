"""Shared conversion API — used by both CLI and GUI."""
import os
from pathlib import Path
import logging

import threading

from cleaner import load_config, load_prompt, create_ai_backend, process_file, SCRIPT_DIR

_STATUS_MAP = {
    "ok": "ok",
    "dry_run": "dry_run",   # preserved so CLI --summary is not a breaking change
    "no_content": "skipped",
    "write_error": "error",
    "error": "error",
}


class _ThreadSafeErrorCapture(logging.Handler):
    """Captures warning-and-above messages per-thread using threading.local."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self._local = threading.local()
        self.set_thread_target()

    def set_thread_target(self):
        self._local.messages = []

    def get_messages(self):
        return getattr(self._local, "messages", [])

    @property
    def messages(self):
        return self.get_messages()

    def emit(self, record):
        messages = getattr(self._local, "messages", None)
        if messages is not None:
            messages.append(record.getMessage())


_ErrorCapture = _ThreadSafeErrorCapture
_GLOBAL_CAPTURE = _ThreadSafeErrorCapture()
_CAPTURE_INITIALIZED = False


def _ensure_capture_registered():
    global _CAPTURE_INITIALIZED
    if not _CAPTURE_INITIALIZED:
        for _log in (logging.getLogger("doc-cleaner"), logging.getLogger("parsers"), logging.getLogger("classifiers")):
            _log.addHandler(_GLOBAL_CAPTURE)
        _CAPTURE_INITIALIZED = True


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


def _build_env(ai="none", config_path=None, prompt_name=None):
    """Load config + create backend + load prompt. Shared setup for GUI and batch calls."""
    if config_path is None:
        import sys
        exe_dir = Path(sys.executable).parent
        cwd_dir = Path.cwd()
        script_dir = Path(SCRIPT_DIR)
        candidates = [
            cwd_dir / "config.json",
            exe_dir / "config.json",
            script_dir / "config.json",
            script_dir.parent / "config.json",
        ]
        for p in candidates:
            if p.exists():
                config_path = str(p)
                break
        else:
            config_path = str(script_dir / "config.json")
    config = load_config(config_path)
    ai_backend = create_ai_backend(ai, config)
    prompt = load_prompt(config, config_path=config_path, prompt_name=prompt_name) if ai_backend else None
    return config, ai_backend, prompt


def _run_one(filepath, ai_backend, prompt, config, output_dir, output_format="md", dry_run=False, skip_existing=False):
    """
    Call process_file and return a GUI-shaped result dict.
    Uses _GLOBAL_CAPTURE to capture warning-and-above messages emitted during conversion.
    """
    _ensure_capture_registered()
    _GLOBAL_CAPTURE.set_thread_target()

    # 增量跳過檢查
    if skip_existing and not dry_run:
        target_out = _resolve_target_output_path(filepath, output_dir, output_format)
        if _check_skip_existing(filepath, target_out):
            return {
                "file": Path(filepath).name,
                "input": str(Path(filepath).resolve()) if not (isinstance(filepath, str) and (filepath.startswith("http://") or filepath.startswith("https://"))) else filepath,
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
        # surface an actionable hint when any parser logged one — e.g. a modern
        # iWork file whose content can't be extracted and should be exported to
        # PDF. Scan all captured messages, not just the last (process_file also
        # logs a generic "No content extracted" line after the parser's hint).
        if any("export" in m.lower() or "匯出" in m for m in captured):
            error_msg = "此檔無可擷取的內嵌內容；請用原 App 匯出 PDF 後再轉換"
        else:
            error_msg = "未擷取到文字內容"
    else:
        error_msg = None

    return {
        "file": Path(filepath).name,
        "input": str(Path(filepath).resolve()) if not (isinstance(filepath, str) and (filepath.startswith("http://") or filepath.startswith("https://"))) else filepath,
        "output": str(Path(out_path).resolve()) if out_path else None,
        "status": status,
        "error": error_msg,
    }


def convert_file(input_path, output_dir=None, ai="none", output_format="md"):
    """
    Convert a single file. Loads config, builds backend, runs extraction.

    Returns: {file, input, output, status, error}
        status: "ok" | "skipped" | "error"
        output_dir=None writes the result beside the source file.
    """
    input_path = str(Path(input_path).resolve()) if not (isinstance(input_path, str) and (input_path.startswith("http://") or input_path.startswith("https://"))) else input_path
    if output_dir is None:
        output_dir = str(Path(input_path).parent)
    config, ai_backend, prompt = _build_env(ai=ai)
    return _run_one(input_path, ai_backend, prompt, config, output_dir, output_format=output_format)


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
    """
    Batch conversion. Builds config + backend + prompt once, reuses across all files.
    Continues past failing files — one error never aborts the batch.
    Supports concurrency, callbacks, cancellation, and skip_existing.

    paths: iterable of file path strings
    output_resolver: callable(abspath) -> output_dir string; None → sibling of each source
    ai: AI backend name ("none" for pure extraction)
    output_format: "md" | "epub" | "both"
    config: pre-processed config dict (optional; None loads default config.json)
    config_path: path to config file (for prompt resolution when config is provided)
    dry_run: skip writing files, preview only
    prompt_name: prompt template name (None uses config, "auto" for content-based selection)
    concurrency: int (optional; concurrency limit)
    on_item_done: callback(result, completed, total) (optional)
    on_progress: callback(completed, total) (optional)
    cancel_event: threading.Event (optional)
    skip_existing: bool (skip if newer output exists)

    Returns: list of {file, input, output, status, error} dicts.
    """
    _ensure_capture_registered()
    if config is None:
        config, ai_backend, prompt = _build_env(ai=ai, config_path=config_path, prompt_name=prompt_name)
    else:
        ai_backend = create_ai_backend(ai, config)
        prompt = load_prompt(config, config_path=config_path, prompt_name=prompt_name) if ai_backend else None

    paths_list = [str(Path(p).resolve()) if not (isinstance(p, str) and (p.startswith("http://") or p.startswith("https://"))) else p for p in paths]
    total = len(paths_list)
    if total == 0:
        return []

    results = [None] * total
    eff_concurrency = _calculate_concurrency(ai=ai, user_concurrency=concurrency, config=config)
    completed_count = 0
    lock = threading.Lock()

    from concurrent.futures import ThreadPoolExecutor

    def _worker(idx, p):
        nonlocal completed_count
        try:
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
        except Exception as e:
            res = {
                "file": Path(p).name,
                "input": p,
                "output": None,
                "status": "error",
                "error": str(e) or "轉換失敗",
            }

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
