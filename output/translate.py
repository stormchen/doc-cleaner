"""Translation helper module for doc-cleaner."""
import json
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger("doc-cleaner")


def translate_en_to_zh_hant(text, chunk_size=1500):
    """
    Translate text into Traditional Chinese (Taiwan terminology).
    Splits long text into paragraph chunks for stable translation API access,
    and applies OpenCC (s2twp) post-processing for Taiwan phrasing.
    """
    if not text or not text.strip():
        return text

    cc = None
    try:
        from opencc import OpenCC
        cc = OpenCC("s2twp")
    except Exception:
        pass

    paragraphs = text.split("\n\n")
    translated_paragraphs = []

    for para in paragraphs:
        if not para.strip():
            translated_paragraphs.append(para)
            continue

        if len(para) > chunk_size:
            sub_lines = para.split("\n")
            translated_sub = []
            for line in sub_lines:
                if not line.strip():
                    translated_sub.append(line)
                else:
                    translated_sub.append(_translate_chunk(line, cc))
            translated_paragraphs.append("\n".join(translated_sub))
        else:
            translated_paragraphs.append(_translate_chunk(para, cc))

    return "\n\n".join(translated_paragraphs)


def _translate_chunk(chunk, cc=None):
    """Translate a single string chunk via Google Translate endpoint with OpenCC conversion."""
    if not chunk or not chunk.strip():
        return chunk

    # Skip Markdown image links, pure numbers, or short code fences
    if chunk.strip().startswith("![") or chunk.strip().startswith("```"):
        return chunk

    try:
        q = urllib.parse.quote(chunk)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-TW&dt=t&q={q}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            raw_body = res.read().decode("utf-8")
            data = json.loads(raw_body)
            if data and isinstance(data, list) and len(data) > 0 and data[0]:
                translated_text = "".join([item[0] for item in data[0] if item and isinstance(item, list) and item[0]])
                if cc:
                    translated_text = cc.convert(translated_text)
                return translated_text
            return chunk
    except Exception as e:
        logger.warning(f"Translation chunk failed ({e}); keeping original text")
        return chunk
