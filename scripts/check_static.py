"""Syntax checks for macapp/static front-end assets.

Usage: python scripts/check_static.py

Verifies:
- index.html parses and every non-void tag is closed
- style.css braces are balanced
- app.js passes `node --check` when Node is available (skipped otherwise)

Exit code 0 = all checks passed; raises AssertionError otherwise.
"""
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "macapp" / "static"

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "source", "track", "wbr",
}


class _TagBalance(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"mismatched </{tag}>")
        else:
            self.stack.pop()


def check_html():
    parser = _TagBalance()
    parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    assert not parser.errors, f"HTML issues: {parser.errors}"
    assert not parser.stack, f"unclosed tags: {parser.stack}"
    print("HTML_STRUCTURE_OK")


def check_css():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    opens, closes = css.count("{"), css.count("}")
    assert opens == closes, f"CSS braces unbalanced: {opens} vs {closes}"
    print("CSS_BRACES_OK")


def check_js():
    node = shutil.which("node")
    if not node:
        print("JS_SYNTAX_SKIPPED (node not installed)")
        return
    result = subprocess.run(
        [node, "--check", str(STATIC / "app.js")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"app.js syntax error:\n{result.stderr}"
    print("JS_SYNTAX_OK")


if __name__ == "__main__":
    check_html()
    check_css()
    check_js()
    print("ALL_CHECKS_PASSED")
