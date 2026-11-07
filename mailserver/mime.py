import base64
import re
from email import policy
from email.parser import BytesParser
from html import escape
from html.parser import HTMLParser
from urllib.parse import unquote


def parse(raw):
    return BytesParser(policy=policy.default).parsebytes(bytes(raw))


def body(message, kind):
    part = message.get_body(preferencelist=(kind,))
    if part is None:
        return ""
    content = part.get_payload(decode=True) or b""
    try:
        text = content.decode(part.get_content_charset() or "utf-8", errors="replace")
    except LookupError:
        text = content.decode("utf-8", errors="replace")
    return text


class FullHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output = []

    def handle_starttag(self, tag, attrs):
        if tag in {"base", "meta"}:
            return
        if tag in {"a", "area"}:
            attrs = [(key, value) for key, value in attrs if key not in {"target", "rel", "ping"}]
            attrs += [("target", "_blank"), ("rel", "noopener noreferrer")]
            self.output.append("<" + tag + "".join(f' {key}="{escape(value or "", quote=True)}"' for key, value in attrs) + ">")
        else:
            self.output.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.output.append(f"</{tag}>")

    def handle_data(self, data):
        self.output.append(data)

    def handle_entityref(self, name):
        self.output.append(f"&{name};")

    def handle_charref(self, name):
        self.output.append(f"&#{name};")

    def handle_comment(self, data):
        self.output.append(f"<!--{data}-->")


def full_html(message):
    html = body(message, "html")
    images = {}
    for part in message.walk():
        cid = str(part.get("Content-ID", "")).strip().strip("<>")
        if cid and part.get_content_maintype() == "image":
            images[cid] = "data:" + part.get_content_type() + ";base64," + base64.b64encode(part.get_payload(decode=True) or b"").decode("ascii")
    html = re.sub(r"cid:([^\s\"'<>\)]+)", lambda match: images.get(unquote(match[1]), match[0]), html, flags=re.IGNORECASE)
    parser = FullHTML()
    parser.feed(html)
    parser.close()
    return '<!doctype html><meta charset="utf-8">' + "".join(parser.output)


def attachments(message):
    result = []
    for index, part in enumerate(message.walk()):
        if part.get_content_disposition() == "attachment" or part.get_filename():
            name = str(part.get_filename() or f"attachment-{index}")
            name = name.replace("\\", "/").split("/")[-1]
            name = "".join(c for c in name if c.isprintable())[:180] or "attachment"
            result.append((index, name, part))
    return result
