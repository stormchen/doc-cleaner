"""Tests for English to Traditional Chinese translation features."""
import os
import argparse
from pathlib import Path
from cleaner import load_prompt, SCRIPT_DIR
from macapp import settings


def test_load_prompt_default():
    """Verify default prompt loading when translate_zh_hant is False."""
    config = {"output": {"translate_zh_hant": False}}
    prompt = load_prompt(config)
    assert "DO NOT translate" in prompt or "document cleaning AI" in prompt


def test_load_prompt_translate_zh_hant():
    """Verify loading translate_zh_hant prompt template when translate_zh_hant is True."""
    config = {"output": {"translate_zh_hant": True}}
    prompt = load_prompt(config)
    assert "Translate English and foreign text into natural, fluent Traditional Chinese" in prompt
    assert "繁體中文" in prompt


def test_settings_translate_zh_hant():
    """Verify settings defaults and validator for translate_zh_hant."""
    assert settings.DEFAULTS.get("translate_zh_hant") is False
    assert settings._valid("translate_zh_hant", True) is True
    assert settings._valid("translate_zh_hant", False) is True
    assert settings._valid("translate_zh_hant", "invalid") is False


def test_cli_translate_zh_hant_flag():
    """Verify cleaner.py CLI parser sets translate_zh_hant in config."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--translate-zh-hant", action="store_true")
    args = parser.parse_args(["--translate-zh-hant"])
    assert args.translate_zh_hant is True
