from mailserver.mime import attachments, body, full_html, parse


def test_unknown_charset_without_preview_limit():
    raw = b'Content-Type: text/plain; charset="made-up-charset"\r\n\r\n' + b'x' * (1024 * 1024 + 20)
    text = body(parse(raw), "plain")
    assert len(text) == 1024 * 1024 + 20


def test_html_preserves_content_but_removes_automatic_navigation():
    raw = b'Content-Type: text/html\r\n\r\n<base href="https://evil.invalid"><meta http-equiv="refresh" content="0;url=https://evil.invalid"><p style="background:url(https://evil.invalid)" onclick="alert(1)">Safe</p><svg><script>bad</script></svg><iframe srcdoc="bad"></iframe>'
    html = full_html(parse(raw))
    assert '<base' not in html and 'http-equiv' not in html
    assert '<p style="background:url(https://evil.invalid)" onclick="alert(1)">Safe</p>' in html
    assert '<svg><script>bad</script></svg>' in html


def test_headers_only_and_missing_body():
    message = parse(b"Subject: headers only\r\n\r\n")
    assert body(message, "plain") == ""
    assert body(message, "html") == ""
    assert not attachments(message)
