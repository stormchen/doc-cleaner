"""
X (Twitter) Article parser — Fetch and convert X articles to Markdown.

Uses X's GraphQL API (TweetResultByRestId) with auth_token and ct0 cookies.
Parses Draft.js content model to clean Markdown.
"""
import re
import json
import logging
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger(__name__)

# Default X WEB API Bearer Token
BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# GraphQL query ID for TweetResultByRestId (may rotate periodically)
DEFAULT_QUERY_ID = "d6YKjvQ920F-D4Y1PruO-A"
GRAPHQL_ENDPOINT = "https://x.com/i/api/graphql"

# Feature flags required by X GraphQL API for TweetResultByRestId
FEATURES = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "freedom_of_speech_promoted_headline_notation_enabled": True,
    "tweet_with_visibility_results_prefer_grok_inline_translation": False,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

ARTICLE_URL_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/(?:[^/]+/status/|[^/]+/article/|i/article/)(\d+)",
    re.IGNORECASE,
)


def is_x_article_url(text):
    """Check if the given string is an X / Twitter Article or Tweet URL."""
    if not isinstance(text, str):
        return False
    text = text.strip()
    return bool(ARTICLE_URL_REGEX.match(text))


def extract_article_id(url):
    """Extract article/tweet ID from X URL."""
    match = ARTICLE_URL_REGEX.match(url.strip())
    if match:
        return match.group(1)
    raise ValueError(f"Invalid X article URL: {url}")


def fetch_x_article_json(article_id, auth_token, ct0, query_id=None):
    """
    Fetch raw article GraphQL response from X API.
    Requires auth_token and ct0 cookies.
    """
    qid = query_id or DEFAULT_QUERY_ID
    url = f"{GRAPHQL_ENDPOINT}/{qid}/TweetResultByRestId"

    variables = {
        "tweetId": str(article_id),
        "includePromotedContent": False,
        "withBirdwatchNotes": False,
        "withVoice": False,
        "withCommunity": False,
    }

    field_toggles = {
        "withArticleRichContentState": True,
        "withArticlePlainText": False,
    }

    params = {
        "variables": json.dumps(variables),
        "features": json.dumps(FEATURES),
        "fieldToggles": json.dumps(field_toggles),
    }

    req_url = f"{url}?{urllib.parse.urlencode(params)}"

    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "x-csrf-token": ct0,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "Cookie": f"auth_token={auth_token}; ct0={ct0}",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Referer": f"https://x.com/i/article/{article_id}",
    }

    req = urllib.request.Request(req_url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = response.read().decode("utf-8")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        logger.error(f"X API HTTP error {e.code}: {body}")
        if e.code == 401 or e.code == 403:
            raise PermissionError("X API 驗證失敗 — 請檢查 .env 或設定檔中的 X_AUTH_TOKEN 與 X_CT0")
        raise RuntimeError(f"X API 請求失敗 (HTTP {e.code})")
    except Exception as e:
        logger.error(f"X API request failed: {e}")
        raise RuntimeError(f"無法存取 X API: {e}")


def render_draftjs_to_markdown(article_result, author_info=None):
    """
    Parse Draft.js content_state and metadata inside article_result to Markdown.
    """
    title = article_result.get("title", "Untitled Article")
    preview_text = article_result.get("preview_text", "")
    
    author_name = ""
    author_handle = ""
    if author_info:
        author_name = author_info.get("name", "")
        author_handle = author_info.get("screen_name", "")

    # Cover image
    cover_url = ""
    cover_media = article_result.get("cover_media")
    if cover_media and isinstance(cover_media, dict):
        media_info = cover_media.get("media_info")
        if media_info and isinstance(media_info, dict):
            cover_url = media_info.get("original_img_url", "")

    # Parse content_state JSON string/dict
    content_state_raw = article_result.get("content_state")
    if isinstance(content_state_raw, str):
        content_state = json.loads(content_state_raw)
    elif isinstance(content_state_raw, dict):
        content_state = content_state_raw
    else:
        content_state = {}

    blocks = content_state.get("blocks", [])
    entity_map_raw = content_state.get("entityMap", {})

    # In X's response, entityMap can be a dict or a list of {key, value} pairs
    entity_map = {}
    if isinstance(entity_map_raw, list):
        for item in entity_map_raw:
            if isinstance(item, dict) and "key" in item:
                entity_map[str(item["key"])] = item.get("value", {})
    elif isinstance(entity_map_raw, dict):
        entity_map = {str(k): v for k, v in entity_map_raw.items()}

    # Media entities lookup
    media_map = {}
    for media_item in article_result.get("media_entities", []):
        m_id = media_item.get("media_id")
        m_info = media_item.get("media_info")
        if m_id and m_info and "original_img_url" in m_info:
            media_map[str(m_id)] = m_info["original_img_url"]

    # Build Markdown header
    lines = []
    lines.append(f"# {title}\n")

    meta_parts = []
    if author_name:
        if author_handle:
            meta_parts.append(f"**作者**: {author_name} (@{author_handle})")
        else:
            meta_parts.append(f"**作者**: {author_name}")

    pub_secs = article_result.get("metadata", {}).get("first_published_at_secs")
    if pub_secs:
        import datetime
        pub_date = datetime.datetime.fromtimestamp(pub_secs, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        meta_parts.append(f"**發布時間**: {pub_date}")

    if meta_parts:
        lines.append(" | ".join(meta_parts) + "\n")

    if cover_url:
        lines.append(f"![Cover Image]({cover_url})\n")

    if preview_text and not blocks:
        lines.append(f"> {preview_text}\n")

    in_list = None  # "unordered" or "ordered"

    for block in blocks:
        block_type = block.get("type", "unstyled")
        text = block.get("text", "")
        inline_styles = block.get("inlineStyleRanges", [])
        entity_ranges = block.get("entityRanges", [])

        # Close active list if block is not a list item
        if in_list and block_type not in ("unordered-list-item", "ordered-list-item"):
            in_list = None
            lines.append("")

        # Apply inline formatting (Bold, Italic, Code, Entities/Links)
        formatted_text = _apply_inline_formatting(text, inline_styles, entity_ranges, entity_map)

        if block_type == "header-one":
            lines.append(f"# {formatted_text}\n")
        elif block_type == "header-two":
            lines.append(f"## {formatted_text}\n")
        elif block_type == "header-three":
            lines.append(f"### {formatted_text}\n")
        elif block_type == "blockquote":
            lines.append(f"> {formatted_text}\n")
        elif block_type == "code-block":
            lines.append(f"```\n{text}\n```\n")
        elif block_type == "unordered-list-item":
            in_list = "unordered"
            indent = "  " * block.get("depth", 0)
            lines.append(f"{indent}- {formatted_text}")
        elif block_type == "ordered-list-item":
            in_list = "ordered"
            indent = "  " * block.get("depth", 0)
            lines.append(f"{indent}1. {formatted_text}")
        elif block_type == "atomic":
            # Image or media entity block
            for er in entity_ranges:
                key = str(er.get("key"))
                entity = entity_map.get(key, {})
                e_type = entity.get("type")
                e_data = entity.get("data", {})
                if e_type in ("IMAGE", "MEDIA", "tweet"):
                    media_id = e_data.get("mediaId") or e_data.get("id")
                    img_url = media_map.get(str(media_id)) or e_data.get("src") or e_data.get("url")
                    if img_url:
                        caption = e_data.get("caption", "Image")
                        lines.append(f"\n![{caption}]({img_url})\n")
        else:
            # unstyled / default paragraph
            if formatted_text.strip():
                lines.append(f"{formatted_text}\n")

    return "\n".join(lines).strip() + "\n"


def _apply_inline_formatting(text, inline_styles, entity_ranges, entity_map):
    """
    Apply inline styles (BOLD, ITALIC, CODE) and entity ranges (LINK) to text.
    Handles character index offsets properly.
    """
    if not text:
        return ""

    chars = list(text)
    # We will build decoration tags at positions
    opens = [[] for _ in range(len(chars) + 1)]
    closes = [[] for _ in range(len(chars) + 1)]

    # Inline styles
    for s in inline_styles:
        offset = s.get("offset", 0)
        length = s.get("length", 0)
        style = s.get("style", "").upper()
        if offset < len(chars) and length > 0:
            end = min(offset + length, len(chars))
            if style == "BOLD":
                opens[offset].append("**")
                closes[end].insert(0, "**")
            elif style == "ITALIC":
                opens[offset].append("*")
                closes[end].insert(0, "*")
            elif style == "CODE":
                opens[offset].append("`")
                closes[end].insert(0, "`")
            elif style == "STRIKETHROUGH":
                opens[offset].append("~~")
                closes[end].insert(0, "~~")

    # Entity ranges (links)
    for er in entity_ranges:
        offset = er.get("offset", 0)
        length = er.get("length", 0)
        key = str(er.get("key"))
        entity = entity_map.get(key, {})
        if offset < len(chars) and length > 0 and entity.get("type") == "LINK":
            end = min(offset + length, len(chars))
            url = entity.get("data", {}).get("url", "")
            if url:
                opens[offset].append("[")
                closes[end].insert(0, f"]({url})")

    result = []
    for i in range(len(chars) + 1):
        if closes[i]:
            result.append("".join(closes[i]))
        if opens[i]:
            result.append("".join(opens[i]))
        if i < len(chars):
            result.append(chars[i])

    return "".join(result)


def load_dotenv_fallback(dotenv_path=".env"):
    import os
    if os.path.exists(dotenv_path):
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("\"'")
                        os.environ[k] = v
        except Exception:
            pass


def parse(url_or_id, config=None):
    """
    Main entry point for X Article parser.
    Given an X article URL or ID and config, returns extracted Markdown string.
    """
    from pathlib import Path
    dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=dotenv_path, override=True)
    except ImportError:
        load_dotenv_fallback(str(dotenv_path))

    config = config or {}
    auth_token = config.get("x_article", {}).get("auth_token") or config.get("x_auth_token")
    ct0 = config.get("x_article", {}).get("ct0") or config.get("x_ct0")

    # Fallback to environment variables if not in config
    import os
    if not auth_token:
        auth_token = (
            os.getenv("X_AUTH_TOKEN") or 
            os.getenv("AUTH_TOKEN") or 
            os.getenv("auth_token") or 
            os.getenv("AUTHTOKEN") or 
            os.getenv("authtoken") or 
            os.getenv("X_AUTHTOKEN") or
            os.getenv("x_authtoken")
        )
    if not ct0:
        ct0 = (
            os.getenv("X_CT0") or 
            os.getenv("CT0") or 
            os.getenv("ct0") or 
            os.getenv("X_CSRF_TOKEN") or 
            os.getenv("csrf_token")
        )

    if auth_token:
        auth_token = str(auth_token).strip("\"' \t\r\n")
    if ct0:
        ct0 = str(ct0).strip("\"' \t\r\n")

    if not auth_token or not ct0:
        raise ValueError(
            "需要 X (Twitter) 驗證憑證！請在 .env 中設定 X_AUTH_TOKEN 與 X_CT0，"
            "或在 config.json / 桌面 App 設定頁面中填入。"
        )

    if is_x_article_url(url_or_id):
        article_id = extract_article_id(url_or_id)
    else:
        article_id = str(url_or_id).strip()

    logger.info(f"Fetching X Article ID: {article_id}")
    data = fetch_x_article_json(article_id, auth_token, ct0)

    # Navigate GraphQL response tree to locate tweet and article result
    tweet_result = (
        data.get("data", {})
        .get("tweetResult", {})
        .get("result", {})
    )

    if not tweet_result:
        raise RuntimeError("X API 回傳的推文/文章資料為空或不存在")

    # Author info
    author_info = {}
    user_results = tweet_result.get("core", {}).get("user_results", {}).get("result", {})
    if "core" in user_results:
        author_info = user_results["core"]
    elif "legacy" in user_results:
        author_info = {
            "name": user_results["legacy"].get("name"),
            "screen_name": user_results["legacy"].get("screen_name"),
        }

    # Article result
    article_obj = tweet_result.get("article", {}).get("article_results", {}).get("result", {})
    if not article_obj:
        # Check if it's longform note tweet
        note_tweet = tweet_result.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
        if note_tweet:
            article_obj = {
                "title": "X Note",
                "content_state": note_tweet.get("content_state"),
                "media_entities": note_tweet.get("media_resources", []),
            }
        else:
            raise RuntimeError("此連結不是有效的 X Article 或 Longform Note 文章")

    markdown = render_draftjs_to_markdown(article_obj, author_info=author_info)
    title = article_obj.get("title", f"X_Article_{article_id}")
    return markdown, title
