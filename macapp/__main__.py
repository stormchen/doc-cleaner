def _run():
    import sys

    try:
        import webview
    except ImportError:
        sys.exit(
            "錯誤：缺少 pywebview。請先安裝：pip install pywebview\n"
            "Error: pywebview is required. Install with: pip install pywebview"
        )

    try:
        from macapp.app import main
    except ImportError as e:
        sys.exit(
            f"錯誤：匯入桌面應用程式模組失敗 ({e})。\n"
            f"請確認已安裝所需依賴：pip install -r requirements.txt\n"
            f"Error: Failed to import desktop app modules ({e}).\n"
            f"Please verify dependencies: pip install -r requirements.txt"
        )

    main()


if __name__ == "__main__":
    _run()

