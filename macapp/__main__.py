def _run():
    import sys
    import traceback

    try:
        import webview
    except Exception as e:
        sys.exit(
            f"錯誤：無法載入 pywebview ({e})。請確認已安裝 pywebview：pip install pywebview\n"
            f"Error: Failed to load pywebview ({e}). Install with: pip install pywebview\n"
            f"{traceback.format_exc()}"
        )

    try:
        from macapp.app import main
    except Exception as e:
        sys.exit(
            f"錯誤：匯入桌面應用程式模組失敗 ({e})。\n"
            f"請確認已安裝所需依賴：pip install -r requirements.txt\n"
            f"Error: Failed to import desktop app modules ({e}).\n"
            f"Please verify dependencies: pip install -r requirements.txt\n"
            f"{traceback.format_exc()}"
        )

    main()


if __name__ == "__main__":
    _run()

