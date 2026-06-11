"""
Markdown output renderer — generates structured Markdown with optional YAML frontmatter.

Two modes:
1. AI mode: renders AI-structured output (title, summary, tags, refined content)
2. Raw mode (--ai none): renders extracted text as-is with minimal formatting
"""
import datetime
import json
import logging

logger = logging.getLogger(__name__)


def _escape_yaml_str(value):
    """Escape a string for safe embedding in double-quoted YAML values."""
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _render_frontmatter(title, description, tags=None, source_path=None):
    """Render YAML frontmatter block shared by AI and raw modes."""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    pub_date = now.strftime("%Y-%m-%d %H:%M+08:00")

    tags = tags or []
    tags_yaml = "\n".join(f'  - "{_escape_yaml_str(t)}"' for t in tags) if tags else ""
    tags_block = f"tags:\n{tags_yaml}" if tags_yaml else "tags: []"

    return (
        f"---\n"
        f'title: "{_escape_yaml_str(title)}"\n'
        f'description: "{_escape_yaml_str(description)}"\n'
        f'pubDate: "{pub_date}"\n'
        f"draft: true\n"
        f"{tags_block}\n"
        f'sourcePath: "{_escape_yaml_str(source_path or "")}"\n'
        f"---\n"
    )


def render_ai_output(data, filename, source_path=None, frontmatter=True):
    """
    Render AI-structured data into Markdown with optional YAML frontmatter.

    Args:
        data: dict with keys: title, summary, refined_markdown, tags (optional)
        filename: original filename (fallback title)
        source_path: original file path (for frontmatter)
        frontmatter: whether to include YAML frontmatter (default: True)

    Returns:
        complete Markdown string
    """
    title = data.get("title") or filename
    summary = data.get("summary") or ""
    refined_markdown = data.get("refined_markdown") or ""
    tags = data.get("tags") or []

    # Defensive conversions to prevent type errors on concatenation
    if not isinstance(title, str):
        title = str(title)

    if not isinstance(summary, str):
        if isinstance(summary, (dict, list)):
            summary = json.dumps(summary, ensure_ascii=False)
        else:
            summary = str(summary)

    if not isinstance(refined_markdown, str):
        if isinstance(refined_markdown, dict):
            # Extract common nested text fields if present
            extracted = False
            for k in ["markdown", "content", "text", "body", "refined_markdown"]:
                if k in refined_markdown and isinstance(refined_markdown[k], str):
                    refined_markdown = refined_markdown[k]
                    extracted = True
                    break
            if not extracted:
                # Otherwise, serialize the dict structure gracefully
                parts_str = []
                for k, v in refined_markdown.items():
                    if isinstance(v, str):
                        parts_str.append(v)
                    elif isinstance(v, (dict, list)):
                        parts_str.append(json.dumps(v, ensure_ascii=False, indent=2))
                if parts_str:
                    refined_markdown = "\n\n".join(parts_str)
                else:
                    refined_markdown = json.dumps(refined_markdown, ensure_ascii=False, indent=2)
        elif isinstance(refined_markdown, list):
            refined_markdown = "\n".join(str(x) for x in refined_markdown)
        else:
            refined_markdown = str(refined_markdown)

    parts = []

    if frontmatter:
        parts.append(_render_frontmatter(title, summary, tags, source_path))

    parts.append(f"# {title}\n")

    if summary:
        parts.append(f"> {summary}\n")

    if refined_markdown:
        parts.append(refined_markdown)

    return "\n".join(parts) + "\n"


def render_raw_output(text, filename, source_path=None, frontmatter=True):
    """
    Render raw extracted text into Markdown (no AI processing).

    Used when --ai none is specified. Outputs the text as-is with
    a simple header and optional frontmatter.
    """
    parts = []

    if frontmatter:
        parts.append(_render_frontmatter(filename, "Raw extraction", source_path=source_path))

    parts.append(f"# {filename}\n")
    parts.append(text)

    return "\n".join(parts) + "\n"
