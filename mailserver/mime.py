from email import policy
from email.parser import BytesParser

import nh3

DISPLAY_LIMIT = 1024 * 1024
TAGS = {"p", "br", "div", "span", "b", "strong", "i", "em", "u", "s", "blockquote", "pre", "code", "ul", "ol", "li", "h1", "h2", "h3", "h4", "hr", "table", "thead", "tbody", "tr", "th", "td", "a"}


def parse(raw):
    return BytesParser(policy=policy.default).parsebytes(bytes(raw))


def body(message, kind):
    part = message.get_body(preferencelist=(kind,))
    if part is None:
        return "", False
    content = part.get_payload(decode=True) or b""
    truncated = len(content) > DISPLAY_LIMIT
    try:
        text = content[:DISPLAY_LIMIT].decode(part.get_content_charset() or "utf-8", errors="replace")
    except LookupError:
        text = content[:DISPLAY_LIMIT].decode("utf-8", errors="replace")
    if kind == "html":
        text = nh3.clean(text, tags=TAGS, attributes={}, clean_content_tags={"script", "style", "svg", "math", "iframe", "object"}, url_schemes=set(), link_rel=None)
    return text, truncated


def attachments(message):
    result = []
    for index, part in enumerate(message.walk()):
        if part.get_content_disposition() == "attachment" or part.get_filename():
            name = str(part.get_filename() or f"attachment-{index}")
            name = name.replace("\\", "/").split("/")[-1]
            name = "".join(c for c in name if c.isprintable())[:180] or "attachment"
            result.append((index, name, part))
    return result
