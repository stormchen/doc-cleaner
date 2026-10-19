import os
import sys
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


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
        "--summary",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0
    combined = proc.stderr + proc.stdout
    assert "Done: 1/1 files processed." in combined
    assert ("✓ test.txt" in combined) or ("\\u2713 test.txt" in combined)


def test_cli_skip_existing_logs(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello incremental", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    out_file = out / "doc.md"
    out_file.write_text("existing converted", encoding="utf-8")

    # Set out_file mtime newer than source
    os.utime(str(out_file), (os.path.getmtime(str(f)) + 100, os.path.getmtime(str(f)) + 100))

    cmd = [
        sys.executable,
        "cleaner.py",
        "-i", str(f),
        "-o", str(out),
        "--ai", "none",
        "--concurrency", "1",
        "--skip-existing",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0
    combined = proc.stderr + proc.stdout
    assert ("⏩ doc.txt (skipped:" in combined) or ("\\u23e9 doc.txt (skipped:" in combined)
    assert "Done: 0/1 files processed (1 skipped)." in combined


def test_cli_batch_summary_json(tmp_path):
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    f1 = in_dir / "f1.txt"
    f2 = in_dir / "f2.txt"
    f1.write_text("file 1 content", encoding="utf-8")
    f2.write_text("file 2 content", encoding="utf-8")

    out_dir = tmp_path / "outputs"
    cmd = [
        sys.executable,
        "cleaner.py",
        "-i", str(in_dir),
        "-o", str(out_dir),
        "--ai", "none",
        "-j", "2",
        "--summary",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0

    # Locate JSON summary from stdout
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    summary_line = lines[-1]
    summary = json.loads(summary_line)
    assert summary["total"] == 2
    assert summary["success"] == 2
    assert summary["skipped"] == 0
    assert summary["failed"] == 0
    assert len(summary["files"]) == 2


def test_cli_skip_existing_exit_code_and_summary(tmp_path):
    """驗證 --skip-existing 啟用時，檔案被跳過視為成功 (EXIT_OK 0)，且 summary 正確統計。"""
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    f1 = in_dir / "file1.txt"
    f1.write_text("content 1", encoding="utf-8")
    f2 = in_dir / "file2.txt"
    f2.write_text("content 2", encoding="utf-8")

    # 預先在 out_dir 建立 file1.md，其 mtime 比 file1.txt 新
    f1_out = out_dir / "file1.md"
    f1_out.write_text("already converted", encoding="utf-8")
    os.utime(str(f1_out), (os.path.getmtime(str(f1)) + 100, os.path.getmtime(str(f1)) + 100))

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
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    summary = json.loads(lines[-1])
    assert summary["total"] == 2
    assert summary["success"] == 1
    assert summary["skipped"] == 1
    assert summary["failed"] == 0
    combined = proc.stderr + proc.stdout
    assert "Done: 1/2 files processed (1 skipped)." in combined

