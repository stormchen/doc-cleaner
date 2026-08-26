"""
doc-cleaner GUI — pywebview desktop app.

Entry point: main()
Bridge:      Api class (exposed as pywebview.api in JS)

The front-end lives in macapp/static/ (index.html + style.css + app.js) and is
loaded as a URL; this module owns only the Python–JS bridge.
"""
import json
import locale
import os
import subprocess
import sys
import threading
import tomllib
from pathlib import Path

import webview

def get_dotenv_path():
    exe_dir = Path(sys.executable).parent
    cwd_dir = Path.cwd()
    script_dir = Path(__file__).resolve().parent
    candidates = [
        cwd_dir / ".env",
        exe_dir / ".env",
        script_dir.parent / ".env",
        script_dir / ".env",
    ]
    for p in candidates:
        if p.exists():
            return p
    return script_dir.parent / ".env"

_dotenv_path = get_dotenv_path()
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_dotenv_path, override=True)
except ImportError:
    try:
        if _dotenv_path.exists():
            with open(_dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip("\"'")
    except Exception:
        pass

import cleaner
import core as _core
from macapp import mdpreview, settings

GITHUB_URL = "https://github.com/notoriouslab/doc-cleaner"

SUPPORTED_TYPES = (
    "支援格式 (*.pdf;*.docx;*.xlsx;*.xls;*.csv;*.txt;*.md;*.pptx;*.dxf;*.doc;*.ppt;*.jsonl;*.numbers;*.pages;*.key;*.epub)",
    "All files (*.*)",
)

_URL_WHITELIST = {GITHUB_URL}

# Static, safe HTML shown in the preview overlay when a file can't be rendered.
_PREVIEW_ERROR_HTML = '<p class="meta">⚠️ 無法預覽此檔案 / Cannot preview this file</p>'


def _static_dir():
    """Directory holding the packaged front-end (index.html/style.css/app.js)."""
    return Path(__file__).resolve().parent / "static"


def _read_version():
    """Read version from pyproject.toml; return 'unknown' on any failure."""
    try:
        toml_path = Path(__file__).parent.parent / "pyproject.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        return data.get("tool", {}).get("briefcase", {}).get("version", "unknown")
    except Exception:
        return "unknown"


def _detect_lang():
    """Detect system locale; return 'zh' for zh-* or Chinese locales, else 'en'."""
    try:
        loc, _ = locale.getlocale()
        if loc:
            loc_lower = loc.lower()
            if loc_lower.startswith("zh") or "chinese" in loc_lower:
                return "zh"
    except Exception:
        pass
    return "en"


class Api:
    """Python–JS bridge. Methods called from JS via pywebview.api.*"""

    _window = None  # assigned by main() after create_window()

    def __init__(self, app_info=None):
        self._batch_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._app_info = app_info or {"version": "unknown", "author": "notoriouslab", "license": "MIT", "url": GITHUB_URL}
        self._settings = settings.load()  # D1: never raises; defaults on missing/corrupt

    def dummy(self, *args, **kwargs):
        """No-op stub for pywebview event callbacks."""
        pass

    def check_gemini_key(self):
        """Return True if GEMINI_API_KEY is configured in environment or config.json."""
        config_path = str(_core.SCRIPT_DIR / "config.json")
        exe_dir = Path(sys.executable).parent
        cwd_dir = Path.cwd()
        script_dir = Path(_core.SCRIPT_DIR)
        candidates = [
            cwd_dir / "config.json",
            exe_dir / "config.json",
            script_dir / "config.json",
            script_dir.parent / "config.json",
        ]
        config_path = str(script_dir / "config.json")
        for p in candidates:
            if p.exists():
                config_path = str(p)
                break

        config_temp = _core.load_config(config_path)
        has_key = bool(os.getenv("GEMINI_API_KEY")) or bool(config_temp.get("ai", {}).get("gemini", {}).get("api_key"))
        return has_key

    def get_app_info(self):
        """Return app metadata dict for the About overlay (D3)."""
        return self._app_info

    # ── preferences (D1/D2) ──────────────────────────────────────────────
    def get_prefs(self):
        """Return the persisted preferences for the front-end to restore on launch."""
        return {
            "output_mode": self._settings.get("output_mode", "sibling"),
            "custom_output_dir": self._settings.get("custom_output_dir"),
            "last_input_dir": self._settings.get("last_input_dir"),
            "output_format": self._settings.get("output_format", "md"),
            "epub_zh_hant": self._settings.get("epub_zh_hant", False),
            "translate_zh_hant": self._settings.get("translate_zh_hant", False),
            "x_auth_token": self._settings.get("x_auth_token"),
            "x_ct0": self._settings.get("x_ct0"),
        }

    def set_x_credentials(self, auth_token, ct0):
        """Persist X credentials (auth_token & ct0)."""
        self._settings["x_auth_token"] = auth_token
        self._settings["x_ct0"] = ct0
        settings.save(self._settings)

    def set_output_mode(self, mode):
        """Persist the chosen output mode (sibling/desktop/custom)."""
        self._settings["output_mode"] = mode
        settings.save(self._settings)

    def set_output_format(self, format_val):
        """Persist the chosen output format (md/epub/both)."""
        self._settings["output_format"] = format_val
        settings.save(self._settings)

    def set_epub_zh_hant(self, val):
        """Persist the chosen epub_zh_hant preference (bool)."""
        self._settings["epub_zh_hant"] = bool(val)
        settings.save(self._settings)

    def set_translate_zh_hant(self, val):
        """Persist the chosen translate_zh_hant preference (bool)."""
        self._settings["translate_zh_hant"] = bool(val)
        settings.save(self._settings)

    def pick_output_folder(self):
        """Open a native folder dialog (seeded at the last custom folder).

        Returns the chosen absolute path (or "" if cancelled). On success,
        persists output_mode="custom" and the chosen folder."""
        seed = self._settings.get("custom_output_dir") or ""
        result = self._window.create_file_dialog(
            webview.FileDialog.FOLDER,
            directory=seed,
        )
        chosen = (list(result)[0] if result else "")
        if chosen:
            self._settings["output_mode"] = "custom"
            self._settings["custom_output_dir"] = chosen
            settings.save(self._settings)
        return chosen

    def _remember_input_dir(self, path):
        """Persist the directory of a picked/dropped source (D2). A dropped
        folder is itself the source directory; a file's directory is its parent."""
        try:
            directory = str(Path(path) if os.path.isdir(path) else Path(path).parent)
        except (TypeError, ValueError):
            return
        if directory and directory != self._settings.get("last_input_dir"):
            self._settings["last_input_dir"] = directory
            settings.save(self._settings)

    def open_url(self, url):
        """Open URL in system browser (D5). Silently rejects unlisted URLs."""
        if url not in _URL_WHITELIST:
            return
        if sys.platform == "darwin":
            subprocess.run(["/usr/bin/open", url], check=False)
        elif sys.platform == "win32":
            os.startfile(url)
        else:
            subprocess.run(["xdg-open", url], check=False)

    def open_github(self):
        """Open the project's GitHub page. Single source of truth for the URL
        (the front-end no longer hardcodes it), so it can't drift from the
        open_url allowlist."""
        self.open_url(GITHUB_URL)

    def pick_files(self):
        """Open native file dialog (seeded at the last input dir, D2).
        Returns list of absolute path strings; remembers the source folder."""
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=self._settings.get("last_input_dir") or "",
            allow_multiple=True,
            file_types=SUPPORTED_TYPES,
        )
        paths = list(result) if result else []
        if paths:
            self._remember_input_dir(paths[0])
        return paths

    def convert(self, paths, output_mode, custom_dir=None, output_format="md"):
        """Start batch conversion on a daemon background thread (non-blocking).
        If a batch is already running the call is silently ignored."""
        if not self._batch_lock.acquire(blocking=False):
            return
        # Fresh batch: clear any stale cancellation request from a prior run.
        self._cancel_event.clear()
        threading.Thread(
            target=self._run_batch_guarded,
            args=(paths, output_mode, custom_dir, output_format),
            daemon=True,
        ).start()

    def cancel_batch(self):
        """Request cancellation of the running batch (new bridge method).

        Cooperative: the batch loop checks the flag between files, so the
        in-flight file finishes and remaining files are skipped. Returns True
        if a batch was running and the request was recorded, False when no
        batch is active."""
        if not self._batch_lock.locked():
            return False
        self._cancel_event.set()
        return True

    def _run_batch_guarded(self, paths, output_mode, custom_dir=None, output_format="md"):
        try:
            self._run_batch(paths, output_mode, custom_dir, output_format)
        finally:
            self._batch_lock.release()

    def _run_batch(self, paths, output_mode, custom_dir=None, output_format="md"):
        """
        Build config+backend once, loop per file pushing progress to JS.
        Resolves symlinks before processing (mirrors CLI's security policy).
        Between files, honors a cancellation request (cancel_batch): remaining
        files are skipped and onCancelled() is pushed instead of onComplete().
        """
        total = len(paths)
        exe_dir = Path(sys.executable).parent
        cwd_dir = Path.cwd()
        script_dir = Path(_core.SCRIPT_DIR)
        candidates = [
            cwd_dir / "config.json",
            exe_dir / "config.json",
            script_dir / "config.json",
            script_dir.parent / "config.json",
        ]
        config_path = str(script_dir / "config.json")
        for p in candidates:
            if p.exists():
                config_path = str(p)
                break
        config_temp = _core.load_config(config_path)
        ai_backend_name = config_temp.get("ai", {}).get("backend", "none")
        
        has_key = False
        if ai_backend_name == "gemini" and (os.getenv("GEMINI_API_KEY") or config_temp.get("ai", {}).get("gemini", {}).get("api_key")):
            has_key = True
        elif ai_backend_name == "openai" and (os.getenv("OPENAI_API_KEY") or config_temp.get("ai", {}).get("openai", {}).get("api_key")):
            has_key = True
        elif ai_backend_name == "groq" and (os.getenv("GROQ_API_KEY") or config_temp.get("ai", {}).get("groq", {}).get("api_key")):
            has_key = True
        elif ai_backend_name == "nvidia" and (os.getenv("NVIDIA_API_KEY") or config_temp.get("ai", {}).get("nvidia", {}).get("api_key")):
            has_key = True
        elif ai_backend_name == "ollama":
            has_key = True

        if not has_key:
            ai_backend_name = "none"

        config, ai_backend, prompt = _core._build_env(ai=ai_backend_name)
        config.setdefault("output", {})["epub_zh_hant"] = self._settings.get("epub_zh_hant", False)
        config.setdefault("output", {})["translate_zh_hant"] = self._settings.get("translate_zh_hant", False)
        if self._settings.get("x_auth_token"):
            config.setdefault("x_article", {})["auth_token"] = self._settings["x_auth_token"]
        if self._settings.get("x_ct0"):
            config.setdefault("x_article", {})["ct0"] = self._settings["x_ct0"]

        if ai_backend:
            prompt = _core.load_prompt(config)

        desktop = str(Path.home() / "Desktop")

        # D2: custom output dir; if it's gone, fall back to sibling + notify once.
        if output_mode == "custom" and not (custom_dir and os.path.isdir(custom_dir)):
            output_mode = "sibling"
            if self._window:
                self._window.evaluate_js("onNotice('fallbackSibling')")

        def _resolver(path):
            if output_mode == "desktop":
                return desktop
            if output_mode == "custom" and custom_dir:  # custom_dir validated above
                return custom_dir
            if path.startswith("http://") or path.startswith("https://"):
                return desktop
            return str(Path(path).parent)  # sibling, and defensive fallback

        for i, path in enumerate(paths):
            if self._cancel_event.is_set():
                break

            from parsers.x_article import is_x_article_url
            if is_x_article_url(path):
                target_path = path
            else:
                target_path = str(Path(path).resolve())

            self._window.evaluate_js(f"onProgress({i + 1}, {total})")
            result = _core._run_one(target_path, ai_backend, prompt, config, _resolver(target_path), output_format=output_format)
            self._window.evaluate_js(
                f"onResult({json.dumps(result, ensure_ascii=False)})"
            )

        if self._cancel_event.is_set():
            self._window.evaluate_js("onCancelled()")
        else:
            self._window.evaluate_js("onComplete()")

    def get_dropped_paths(self):
        """Return supported file paths from a drop event (D3).

        Directories are expanded recursively into their supported files; loose
        files are kept if supported. Remembers the source folder and notifies
        the front-end when a folder expansion hits the recursion cap."""
        from webview.dom import _dnd_state
        raw = [p for _name, p in _dnd_state["paths"]]
        _dnd_state["paths"].clear()

        expanded = []
        capped = False
        for p in raw:
            if os.path.isdir(p):
                # Use the recursive collector's accurate capped flag (not a
                # len()>=cap heuristic, which false-positives at exactly the cap).
                collected, was_capped = cleaner._collect_dir_recursive(p, os.path.realpath(p))
                if was_capped:
                    capped = True
                expanded.extend(collected)
            elif os.path.isfile(p):
                if os.path.splitext(p)[1].lower() in cleaner.SUPPORTED_EXTENSIONS:
                    expanded.append(os.path.realpath(p))

        # De-duplicate, preserving order.
        seen = set()
        result = []
        for p in expanded:
            if p not in seen:
                seen.add(p)
                result.append(p)

        if raw:
            self._remember_input_dir(raw[0])
        if capped and self._window:
            self._window.evaluate_js(f"onNotice('cap', {cleaner.MAX_RECURSIVE_FILES})")
        return result

    def reveal_in_finder(self, path):
        """Reveal file in platform file manager."""
        from parsers._platform import reveal_in_file_manager
        reveal_in_file_manager(path)

    def preview_markdown(self, path):
        """Read a produced .md and return safe rendered HTML for the preview
        overlay (D5). Path-checked (absolute, existing regular file) and
        size-capped before reading; never raises — returns an escaped error
        message string on any failure."""
        try:
            if not path or not os.path.isabs(path):
                return _PREVIEW_ERROR_HTML
            real = os.path.realpath(path)
            if not os.path.isfile(real):
                return _PREVIEW_ERROR_HTML
            if os.path.getsize(real) > mdpreview.MAX_PREVIEW_BYTES:
                return _PREVIEW_ERROR_HTML
            with open(real, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            return mdpreview.render(text)
        except Exception:
            return _PREVIEW_ERROR_HTML


def main():
    from webview.dom import _dnd_state
    _dnd_state["num_listeners"] = 1

    # Detect locale and build app info once (D1, D3)
    lang = _detect_lang() if sys.platform in ("darwin", "win32") else "en"
    is_macos = sys.platform in ("darwin", "win32")
    app_info = {
        "version": _read_version(),
        "author": "notoriouslab",
        "license": "MIT",
        "url": GITHUB_URL,
    }

    api = Api(app_info)
    index_url = (_static_dir() / "index.html").as_uri()
    window = webview.create_window(
        "Doc Cleaner",
        url=index_url,
        js_api=api,
        width=640,
        height=800,
        min_size=(520, 620),
    )
    api._window = window

    # Inject initial language after page loads (D1, D2)
    is_macos_js = "true" if is_macos else "false"
    window.events.loaded += lambda: window.evaluate_js(
        f"init('{lang}', {is_macos_js})"
    )

    webview.start(debug=False)
