import os
import sys
import json
import time
import threading
import subprocess
from pathlib import Path
import pytest

from core import convert_files

REPO_ROOT = Path(__file__).resolve().parent.parent


def _create_sample_files(base_dir):
    """建立包含不同支援格式的真實測試檔案（不同檔名避免 stem 衝突）。"""
    files = {}

    # 1. 純文字檔案 (.txt)
    txt_path = base_dir / "doc_text.txt"
    txt_path.write_text("這是純文字文件內容。\n包含第二行文字。", encoding="utf-8")
    files["txt"] = str(txt_path)

    # 2. Markdown 檔案 (.md)
    md_path = base_dir / "doc_markdown.md"
    md_path.write_text("# 標題一\n\n- 項目 A\n- 項目 B\n\n內文段落說明。", encoding="utf-8")
    files["md"] = str(md_path)

    # 3. CSV 檔案 (.csv)
    csv_path = base_dir / "doc_table.csv"
    csv_path.write_text("項目,數量,單價\n蘋果,10,25\n香蕉,5,15\n", encoding="utf-8")
    files["csv"] = str(csv_path)

    # 4. JSONL 檔案 (.jsonl) - Claude Code transcript 格式
    jsonl_path = base_dir / "doc_transcript.jsonl"
    transcript_lines = [
        {
            "type": "user",
            "sessionId": "e2e_session",
            "timestamp": "2026-10-19T10:00:00.000Z",
            "message": {"role": "user", "content": "請幫我分析這份報告。"}
        },
        {
            "type": "assistant",
            "sessionId": "e2e_session",
            "timestamp": "2026-10-19T10:00:05.000Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "好的，以下是分析結果..."}]}
        }
    ]
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for line in transcript_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    files["jsonl"] = str(jsonl_path)

    return files


def test_batch_e2e_mixed_formats_concurrent(tmp_path):
    """端到端測試 1：多種支援格式檔案（.txt, .md, .csv, .jsonl）混合批次並行轉換。"""
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()

    sample_files = _create_sample_files(in_dir)
    input_paths = [
        sample_files["txt"],
        sample_files["md"],
        sample_files["csv"],
        sample_files["jsonl"],
    ]

    results = convert_files(
        input_paths,
        output_resolver=lambda _: str(out_dir),
        ai="none",
        concurrency=4,
    )

    # 1. 驗證結果總數與順序嚴格一致
    assert len(results) == len(input_paths)
    for res, orig_path in zip(results, input_paths):
        assert res["input"] == orig_path
        assert res["file"] == Path(orig_path).name
        assert res["status"] == "ok"
        assert res["error"] is None
        assert res["output"] is not None
        assert os.path.exists(res["output"])

    # 2. 驗證各輸出檔內容正確落地
    txt_out = (out_dir / "doc_text.md").read_text(encoding="utf-8")
    assert "這是純文字文件內容" in txt_out

    md_out = (out_dir / "doc_markdown.md").read_text(encoding="utf-8")
    assert "項目 A" in md_out

    csv_out = (out_dir / "doc_table.md").read_text(encoding="utf-8")
    assert "蘋果" in csv_out

    jsonl_out = (out_dir / "doc_transcript.md").read_text(encoding="utf-8")
    assert "請幫我分析這份報告" in jsonl_out


def test_batch_e2e_strict_order_preservation(tmp_path):
    """端到端測試 2：驗證並發數有效，回傳結果順序嚴格符合輸入順序（即使非同步完成）。"""
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()

    count = 8
    # 建立 8 個具有不同檔名與內容的檔案
    created_paths = []
    for i in range(count):
        f = in_dir / f"doc_{i:02d}.txt"
        f.write_text(f"Document content number {i} " * (10 + i * 5), encoding="utf-8")
        created_paths.append(str(f))

    # 故意打亂傳入順序（例如倒序或非排序順序）
    shuffled_paths = [created_paths[i] for i in [5, 2, 7, 0, 4, 1, 6, 3]]

    completed_order = []
    progress_records = []

    def on_item(res, done, total):
        completed_order.append(res["file"])

    def on_prog(done, total):
        progress_records.append((done, total))

    results = convert_files(
        shuffled_paths,
        output_resolver=lambda _: str(out_dir),
        ai="none",
        concurrency=4,
        on_item_done=on_item,
        on_progress=on_prog,
    )

    # 1. 回傳結果的順序必須 100% 嚴格符合 shuffled_paths
    assert len(results) == count
    expected_filenames = [Path(p).name for p in shuffled_paths]
    assert [r["file"] for r in results] == expected_filenames
    assert [r["input"] for r in results] == shuffled_paths
    assert all(r["status"] == "ok" for r in results)

    # 2. 進度計數必須從 1 到 count 逐步完成
    assert len(progress_records) == count
    assert progress_records[-1] == (count, count)
    assert len(completed_order) == count


def test_batch_e2e_skip_existing_incremental(tmp_path):
    """端到端測試 3：驗證 --skip-existing 增量行為在多檔案混合環境下的正確性。"""
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()

    # 建立 4 個不同檔名的檔案
    files = []
    for name in ["alpha", "beta", "gamma", "delta"]:
        p = in_dir / f"{name}.txt"
        p.write_text(f"Content of {name}", encoding="utf-8")
        files.append(str(p))

    # 第一階段：全量轉換，全部產出
    res_phase1 = convert_files(
        files,
        output_resolver=lambda _: str(out_dir),
        ai="none",
        concurrency=2,
        skip_existing=True,
    )
    assert len(res_phase1) == 4
    assert all(r["status"] == "ok" for r in res_phase1)

    # 檢查第一階段檔案確實存在於磁碟
    for r in res_phase1:
        assert os.path.exists(r["output"])

    # 第二階段：模擬真實使用者的各種操作狀態
    # 檔案 A (alpha): 維持不變 -> 預期 skipped
    # 檔案 B (beta): 來源檔修改更新 -> 預期 ok（重新轉換）
    time.sleep(0.05)
    beta_src = in_dir / "beta.txt"
    beta_src.write_text("Updated beta content!", encoding="utf-8")
    # 刻意將 beta 來源檔的時間設為未來，確保新於輸出檔
    future_time = time.time() + 10
    os.utime(str(beta_src), (future_time, future_time))

    # 檔案 C (gamma): 輸出檔遭刪除 -> 預期 ok（重新產生）
    gamma_out = out_dir / "gamma.md"
    os.remove(str(gamma_out))

    # 檔案 D (delta): 維持不變 -> 預期 skipped

    res_phase2 = convert_files(
        files,
        output_resolver=lambda _: str(out_dir),
        ai="none",
        concurrency=2,
        skip_existing=True,
    )

    assert len(res_phase2) == 4
    assert [r["file"] for r in res_phase2] == ["alpha.txt", "beta.txt", "gamma.txt", "delta.txt"]

    # 驗證個別檔案狀態
    assert res_phase2[0]["status"] == "skipped"
    assert "跳過" in (res_phase2[0]["error"] or "")

    assert res_phase2[1]["status"] == "ok"
    assert "Updated beta content!" in Path(res_phase2[1]["output"]).read_text(encoding="utf-8")

    assert res_phase2[2]["status"] == "ok"
    assert os.path.exists(str(gamma_out))

    assert res_phase2[3]["status"] == "skipped"
    assert "跳過" in (res_phase2[3]["error"] or "")


def test_batch_e2e_cancel_event_graceful_shutdown(tmp_path):
    """端到端測試 4：驗證 cancel_event 在並發下安全退出，不遺失項目且未執行項正確標記 cancelled。"""
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()

    files = []
    for i in range(10):
        p = in_dir / f"file_{i:02d}.txt"
        p.write_text(f"Data line {i}", encoding="utf-8")
        files.append(str(p))

    cancel_event = threading.Event()

    def on_item(res, done, total):
        # 當完成 2 個項目時觸發取消事件
        if done >= 2:
            cancel_event.set()

    results = convert_files(
        files,
        output_resolver=lambda _: str(out_dir),
        ai="none",
        concurrency=1,  # 單執行緒以精確控制取消時機
        cancel_event=cancel_event,
        on_item_done=on_item,
    )

    # 1. 驗證回傳串列長度仍然與輸入一致（10 筆）
    assert len(results) == 10
    # 2. 順序仍與輸入一致
    assert [r["file"] for r in results] == [f"file_{i:02d}.txt" for i in range(10)]

    # 3. 至少有被取消的檔案
    statuses = [r["status"] for r in results]
    assert "cancelled" in statuses
    assert "ok" in statuses

    # 4. 被取消的項目包含正確的錯誤訊息
    for r in results:
        if r["status"] == "cancelled":
            assert r["error"] == "使用者取消"
            assert r["output"] is None


def test_batch_e2e_error_capture_and_isolation(tmp_path):
    """端到端測試 5：驗證並行轉換中錯誤檔案被安全捕獲且不污染其他執行緒的日誌或結果。"""
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()

    f1 = in_dir / "valid_1.txt"
    f1.write_text("Valid content 1", encoding="utf-8")

    # 建立一個不存在的檔案路徑，會觸發讀取例外並產生 error 狀態
    f_err = in_dir / "missing_file.txt"

    f2 = in_dir / "valid_2.txt"
    f2.write_text("Valid content 2", encoding="utf-8")

    files = [str(f1), str(f_err), str(f2)]

    results = convert_files(
        files,
        output_resolver=lambda _: str(out_dir),
        ai="none",
        concurrency=3,
    )

    assert len(results) == 3
    assert [r["file"] for r in results] == ["valid_1.txt", "missing_file.txt", "valid_2.txt"]

    # f1 正常
    assert results[0]["status"] == "ok"
    assert results[0]["error"] is None
    assert os.path.exists(results[0]["output"])

    # missing_file.txt 錯誤安全捕獲，不中斷整體執行
    assert results[1]["status"] == "error"
    assert results[1]["output"] is None
    assert results[1]["error"] is not None
    assert "missing_file.txt" in results[1]["error"] or "no such file" in results[1]["error"].lower()

    # f2 正常，不受前一個檔案錯誤影響，且 error 仍為 None
    assert results[2]["status"] == "ok"
    assert results[2]["error"] is None
    assert os.path.exists(results[2]["output"])


def test_batch_e2e_cli_real_execution(tmp_path):
    """端到端測試 6：驗證 CLI cleaner.py --concurrency 2 --skip-existing --summary 真實執行。"""
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()

    f1 = in_dir / "t1.txt"
    f1.write_text("File 1 content", encoding="utf-8")
    f2 = in_dir / "t2.txt"
    f2.write_text("File 2 content", encoding="utf-8")
    f3 = in_dir / "t3.md"
    f3.write_text("# Markdown file 3\n\nSome body.", encoding="utf-8")

    cmd = [
        sys.executable,
        "cleaner.py",
        "-i", str(in_dir),
        "-o", str(out_dir),
        "--ai", "none",
        "-j", "2",
        "--skip-existing",
        "--summary",
    ]

    # --- 第一次執行：全部成功轉換 ---
    proc1 = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc1.returncode == 0, f"CLI execution failed: {proc1.stderr}"

    # 解析 stdout 的 JSON summary
    stdout_lines1 = [line.strip() for line in proc1.stdout.splitlines() if line.strip()]
    assert len(stdout_lines1) > 0
    summary1 = json.loads(stdout_lines1[-1])

    assert summary1["total"] == 3
    assert summary1["success"] == 3
    assert summary1["failed"] == 0
    assert len(summary1["files"]) == 3
    assert all(item["status"] == "ok" for item in summary1["files"])

    # 驗證輸出日誌包含處理進度符號
    combined_log1 = proc1.stderr + proc1.stdout
    assert "Done: 3/3 files processed." in combined_log1

    # --- 第二次執行：觸發增量跳過 --skip-existing ---
    proc2 = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))

    stdout_lines2 = [line.strip() for line in proc2.stdout.splitlines() if line.strip()]
    assert len(stdout_lines2) > 0
    summary2 = json.loads(stdout_lines2[-1])

    # 驗證所有檔案皆為 skipped
    assert summary2["total"] == 3
    assert len(summary2["files"]) == 3
    assert all(item["status"] == "skipped" for item in summary2["files"])

    # 驗證輸出日誌包含跳過符號
    combined_log2 = proc2.stderr + proc2.stdout
    assert ("⏩" in combined_log2) or ("\\u23e9" in combined_log2)


def test_batch_e2e_cli_readme_execution(tmp_path):
    """端到端測試 7：驗證 cleaner.py 針對單一 README.md 執行 -j 2 --skip-existing --summary。"""
    out_dir = tmp_path / "readme_out"
    out_dir.mkdir()

    cmd = [
        sys.executable,
        "cleaner.py",
        "-i", "README.md",
        "-o", str(out_dir),
        "--ai", "none",
        "-j", "2",
        "--skip-existing",
        "--summary",
    ]

    # 第一次執行：產生輸出檔
    proc1 = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc1.returncode == 0
    summary1 = json.loads([line.strip() for line in proc1.stdout.splitlines() if line.strip()][-1])
    assert summary1["total"] == 1
    assert summary1["files"][0]["status"] == "ok"

    # 第二次執行：增量跳過
    proc2 = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    summary2 = json.loads([line.strip() for line in proc2.stdout.splitlines() if line.strip()][-1])
    assert summary2["total"] == 1
    assert summary2["files"][0]["status"] == "skipped"
