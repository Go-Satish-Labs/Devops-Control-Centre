"""Escaping helpers. All dynamic text placed in SVG, Markdown or CSV goes through these."""
import re
from xml.sax.saxutils import escape

_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def xml_escape(value) -> str:
    text = _INVALID_XML.sub("", "" if value is None else str(value))
    return escape(text, {'"': "&quot;", "'": "&apos;"})


def truncate(value, limit: int) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: max(limit - 1, 0)] + "…"


def md_escape(value) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\\", "\\\\")
    for char in "|`*_<>[]#":
        text = text.replace(char, "\\" + char)
    return text.replace("\r", " ").replace("\n", " ")


def csv_safe(value) -> str:
    """Neutralises spreadsheet formula injection by prefixing risky cells."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text
