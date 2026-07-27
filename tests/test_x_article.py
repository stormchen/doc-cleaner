"""
Tests for X (Twitter) Article parser — parsers/x_article.py.
"""
import pytest
from parsers.x_article import (
    is_x_article_url,
    extract_article_id,
    render_draftjs_to_markdown,
    parse,
)


def test_is_x_article_url():
    valid_urls = [
        "https://x.com/elonmusk/article/1234567890",
        "https://twitter.com/user/article/987654321012345",
        "https://x.com/i/article/1234567890",
        "http://x.com/username/status/1234567890",
    ]
    for url in valid_urls:
        assert is_x_article_url(url) is True

    invalid_urls = [
        "https://google.com",
        "https://x.com/home",
        "C:\\documents\\report.pdf",
        "./output/statement.pdf",
    ]
    for url in invalid_urls:
        assert is_x_article_url(url) is False


def test_extract_article_id():
    assert extract_article_id("https://x.com/elonmusk/article/1234567890") == "1234567890"
    assert extract_article_id("https://twitter.com/user/article/9876543210") == "9876543210"
    assert extract_article_id("https://x.com/i/article/5555555555") == "5555555555"

    with pytest.raises(ValueError):
        extract_article_id("https://x.com/invalid_url")


def test_render_draftjs_to_markdown():
    mock_article_result = {
        "title": "Test Article Title",
        "preview_text": "This is a preview of the test article.",
        "cover_media": {
            "media_info": {
                "original_img_url": "https://pbs.twimg.com/media/cover.jpg"
            }
        },
        "content_state": {
            "blocks": [
                {
                    "type": "header-one",
                    "text": "Introduction",
                    "inlineStyleRanges": [],
                    "entityRanges": [],
                },
                {
                    "type": "unstyled",
                    "text": "This is bold text inside a paragraph.",
                    "inlineStyleRanges": [
                        {"offset": 8, "length": 4, "style": "BOLD"}
                    ],
                    "entityRanges": [],
                },
                {
                    "type": "unordered-list-item",
                    "text": "First item",
                    "depth": 0,
                },
                {
                    "type": "unordered-list-item",
                    "text": "Second item",
                    "depth": 0,
                },
            ],
            "entityMap": {},
        },
    }

    mock_author_info = {
        "name": "Jane Doe",
        "screen_name": "janedoe",
    }

    md = render_draftjs_to_markdown(mock_article_result, author_info=mock_author_info)

    assert "# Test Article Title" in md
    assert "**作者**: Jane Doe (@janedoe)" in md
    assert "![Cover Image](https://pbs.twimg.com/media/cover.jpg)" in md
    assert "# Introduction" in md
    assert "This is **bold** text inside a paragraph." in md
    assert "- First item" in md
def test_parse_missing_credentials(monkeypatch):
    # Stub dotenv loading to prevent reloading real credentials from disk during test
    monkeypatch.setattr("parsers.x_article.load_dotenv_fallback", lambda *args, **kwargs: None)
    try:
        import dotenv
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)
    except ImportError:
        pass

    # Clear all possible environment variables
    for key in ["X_AUTH_TOKEN", "AUTH_TOKEN", "auth_token", "AUTHTOKEN", "authtoken", "X_AUTHTOKEN", "x_authtoken",
                "X_CT0", "CT0", "ct0", "X_CSRF_TOKEN", "csrf_token"]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError, match="需要 X \\(Twitter\\) 驗證憑證"):
        parse("https://x.com/user/article/1234567890", config={})
