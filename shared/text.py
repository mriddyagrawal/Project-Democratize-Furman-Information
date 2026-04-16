"""Shared text cleaning utilities."""

import html
import re


def clean_text(text: str | None) -> str:
    """Normalize whitespace: collapse \\n, \\t, \\r, multiple spaces into single spaces."""
    if not text:
        return ""
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def strip_html(text: str | None) -> str:
    """Remove HTML tags, decode entities, normalize whitespace."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"</p>\s*<p>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return clean_text(text)
