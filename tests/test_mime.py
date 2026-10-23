from mailserver.mime import DISPLAY_LIMIT, attachments, body, parse


def test_unknown_charset_and_preview_limit():
    raw = b'Content-Type: text/plain; charset="made-up-charset"\r\n\r\n' + b'x' * (DISPLAY_LIMIT + 20)
    text, truncated = body(parse(raw), "plain")
    assert len(text) == DISPLAY_LIMIT
    assert truncated


def test_html_removes_navigation_css_and_markup():
    raw = b'Content-Type: text/html\r\n\r\n<base href="https://evil.invalid"><meta http-equiv="refresh" content="0;url=https://evil.invalid"><p style="background:url(https://evil.invalid)" onclick="alert(1)">Safe</p><svg><script>bad</script></svg><iframe srcdoc="bad"></iframe>'
    html, _ = body(parse(raw), "html")
    assert html == "<p>Safe</p>"


def test_headers_only_and_missing_body():
    message = parse(b"Subject: headers only\r\n\r\n")
    assert body(message, "plain") == ("", False)
    assert body(message, "html") == ("", False)
    assert not attachments(message)
