"""Unit tests for Api._convert_batch_worker delegation to core.convert_files."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure webview mock is present even if pywebview is not installed in the environment
if "webview" not in sys.modules:
    sys.modules["webview"] = MagicMock()

from macapp.app import Api


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path_factory, monkeypatch):
    """Isolate preferences I/O to a temp dir so Api tests never touch real settings."""
    from macapp import settings as _settings
    d = tmp_path_factory.mktemp("appdata")
    monkeypatch.setattr(_settings, "app_data_dir", lambda: str(d))


def _make_api():
    api = Api()
    api._window = MagicMock()
    return api


def test_convert_batch_worker_delegates_to_core(tmp_path):
    api = _make_api()

    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("content 1", encoding="utf-8")
    f2.write_text("content 2", encoding="utf-8")

    api._convert_batch_worker([str(f1), str(f2)], output_mode="custom", custom_dir=str(tmp_path))

    js_calls = [call.args[0] for call in api._window.evaluate_js.call_args_list]
    assert any("onProgress" in c for c in js_calls), "Should push onProgress"
    assert any("onResult" in c for c in js_calls), "Should push onResult"
    assert any("onComplete()" in c for c in js_calls), "Should push onComplete"


def test_convert_batch_worker_passes_proper_kwargs_to_convert_files(tmp_path):
    api = _make_api()
    paths = [str(tmp_path / "x.txt")]

    with patch("macapp.app._core.convert_files") as mock_convert:
        api._convert_batch_worker(paths, output_mode="sibling")
        assert mock_convert.called, "_core.convert_files should be called"
        args, kwargs = mock_convert.call_args
        assert args[0] == paths
        assert callable(kwargs.get("output_resolver"))
        assert kwargs.get("cancel_event") is api._cancel_event
        assert callable(kwargs.get("on_item_done"))


def test_convert_batch_worker_on_item_done_callback(tmp_path):
    api = _make_api()
    f = tmp_path / "item.txt"
    f.write_text("hello", encoding="utf-8")

    fake_result = {
        "file": "item.txt",
        "input": str(f),
        "output": str(tmp_path / "item.md"),
        "status": "ok",
        "error": None,
    }

    # Intercept convert_files to trigger the on_item_done callback directly
    def _fake_convert_files(*args, **kwargs):
        on_done = kwargs.get("on_item_done")
        if on_done:
            on_done(fake_result, 1, 1)
        return [fake_result]

    with patch("macapp.app._core.convert_files", side_effect=_fake_convert_files):
        api._convert_batch_worker([str(f)], output_mode="sibling")

    js_calls = [call.args[0] for call in api._window.evaluate_js.call_args_list]
    assert "onProgress(1, 1)" in js_calls
    matching_result = [c for c in js_calls if c.startswith("onResult(")]
    assert len(matching_result) == 1
    payload = json.loads(matching_result[0][len("onResult("):-1])
    assert payload["file"] == "item.txt"
    assert payload["status"] == "ok"


def test_convert_batch_worker_handles_cancellation(tmp_path):
    api = _make_api()
    f1 = tmp_path / "c1.txt"
    f2 = tmp_path / "c2.txt"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")

    def _cancelling_convert(*args, **kwargs):
        api._cancel_event.set()
        return []

    with patch("macapp.app._core.convert_files", side_effect=_cancelling_convert):
        api._convert_batch_worker([str(f1), str(f2)], output_mode="sibling")

    js_calls = [call.args[0] for call in api._window.evaluate_js.call_args_list]
    assert any("onCancelled()" in c for c in js_calls), "Should notify onCancelled"
    assert not any("onComplete()" in c for c in js_calls), "Should not notify onComplete when cancelled"


def test_convert_batch_worker_output_resolver(tmp_path):
    api = _make_api()
    desktop = str(Path.home() / "Desktop")
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()

    captured_resolvers = []

    def _capture_convert(*args, **kwargs):
        captured_resolvers.append(kwargs.get("output_resolver"))
        return []

    with patch("macapp.app._core.convert_files", side_effect=_capture_convert):
        # 1. desktop mode
        api._convert_batch_worker(["/tmp/file.txt"], output_mode="desktop")
        resolver_desktop = captured_resolvers[-1]
        assert resolver_desktop("/tmp/file.txt") == desktop

        # 2. sibling mode
        api._convert_batch_worker(["/tmp/sub/file.txt"], output_mode="sibling")
        resolver_sibling = captured_resolvers[-1]
        assert resolver_sibling("/tmp/sub/file.txt") == str(Path("/tmp/sub/file.txt").parent)

        # 3. URL input always targets desktop
        assert resolver_sibling("https://example.com/article") == desktop

        # 4. custom mode with valid dir
        api._convert_batch_worker(["/tmp/file.txt"], output_mode="custom", custom_dir=str(custom_dir))
        resolver_custom = captured_resolvers[-1]
        assert resolver_custom("/tmp/file.txt") == str(custom_dir)

        # 5. custom mode with invalid dir falls back to sibling and notifies
        api._window.reset_mock()
        api._convert_batch_worker(["/tmp/sub/file.txt"], output_mode="custom", custom_dir=str(tmp_path / "nonexistent"))
        resolver_fallback = captured_resolvers[-1]
        assert resolver_fallback("/tmp/sub/file.txt") == str(Path("/tmp/sub/file.txt").parent)
        notice_calls = [c.args[0] for c in api._window.evaluate_js.call_args_list if "onNotice" in c.args[0]]
        assert any("fallbackSibling" in c for c in notice_calls)


def test_run_batch_backward_compatible_alias(tmp_path):
    api = _make_api()
    f = tmp_path / "legacy.txt"
    f.write_text("legacy", encoding="utf-8")

    with patch.object(api, "_convert_batch_worker", return_value=[]) as mock_worker:
        api._run_batch([str(f)], output_mode="sibling")
        assert mock_worker.called, "_run_batch should forward to _convert_batch_worker"
