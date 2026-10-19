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
