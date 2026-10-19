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

