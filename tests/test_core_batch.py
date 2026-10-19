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


def test_resolve_target_output_path(tmp_path):
    import os
    from core import _resolve_target_output_path

    src = str(tmp_path / "document.pdf")
    out_dir = str(tmp_path / "out")

    assert _resolve_target_output_path(src, out_dir, "md") == str(tmp_path / "out" / "document.md")
    assert _resolve_target_output_path(src, out_dir, "epub") == str(tmp_path / "out" / "document.epub")
    assert _resolve_target_output_path(src, out_dir, "both") == str(tmp_path / "out" / "document.md")

    # X Article URL stem resolution
    x_url = "https://x.com/user/article/123456789"
    assert _resolve_target_output_path(x_url, out_dir, "md") == str(tmp_path / "out" / "x_article_123456789.md")


def test_check_skip_existing(tmp_path):
    import os
    import time
    from core import _check_skip_existing

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

    # URL 永遠不跳過
    assert not _check_skip_existing("https://x.com/user/article/123", str(out))


def test_convert_files_concurrent_order_and_callbacks(tmp_path):
    import os
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
    import os
    import threading
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


def test_convert_files_skip_existing(tmp_path):
    import os
    from core import convert_files

    f1 = tmp_path / "skip_doc1.txt"
    f1.write_text("doc1", encoding="utf-8")
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir, exist_ok=True)

    # 第一次執行：產生輸出檔
    res1 = convert_files([str(f1)], output_resolver=lambda _: out_dir, ai="none", skip_existing=False)
    assert res1[0]["status"] == "ok"
    assert os.path.exists(res1[0]["output"])

    # 第二次執行：開啟 skip_existing，應跳過
    res2 = convert_files([str(f1)], output_resolver=lambda _: out_dir, ai="none", skip_existing=True)
    assert res2[0]["status"] == "skipped"
    assert res2[0]["error"] == "已存在最新輸出檔，跳過"


def test_convert_files_empty_and_callback_exceptions(tmp_path):
    from core import convert_files

    # 1. 空列表回傳空列表
    assert convert_files([]) == []

    # 2. 回調丟出例外不應中斷轉換
    f = tmp_path / "cb_doc.txt"
    f.write_text("content", encoding="utf-8")
    out_dir = str(tmp_path / "out")

    def buggy_prog(completed, total):
        raise RuntimeError("Buggy progress")

    def buggy_item(res, completed, total):
        raise RuntimeError("Buggy item")

    results = convert_files(
        [str(f)],
        output_resolver=lambda _: out_dir,
        ai="none",
        on_progress=buggy_prog,
        on_item_done=buggy_item,
    )
    assert len(results) == 1
    assert results[0]["status"] == "ok"



