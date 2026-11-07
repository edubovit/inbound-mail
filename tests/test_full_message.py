from email.message import EmailMessage

import pytest
from django.test import Client

from mailserver.mime import full_html, parse
from mailserver.models import Message
from mailserver.storage import deliver

pytestmark = pytest.mark.django_db


def test_full_view_requires_explicit_choice_each_visit(client, alice, raw):
    deliver([alice.address], raw)
    item = Message.objects.get()
    path = f"/messages/{item.pk}/"
    client.force_login(alice)
    for url in [path, path + "?view=full"]:
        response = client.get(url)
        assert b"<iframe" not in response.content
        assert b"Show full view" in response.content
    response = client.post(path, {"view": "full"})
    assert b'<iframe title="Email HTML" sandbox="allow-popups allow-popups-to-escape-sandbox"' in response.content
    assert b"Show plain text" in response.content
    assert b"<iframe" not in client.get(path).content
    item.refresh_from_db()
    assert not item.is_read and bytes(item.raw) == raw
    protected = Client(enforce_csrf_checks=True)
    protected.force_login(alice)
    assert protected.post(path, {"view": "full"}).status_code == 403


def test_complete_plain_and_html_only_source(client, alice):
    message = EmailMessage()
    tail = 'TAIL <img src="https://example.invalid/image"> https://example.org/path'
    message.set_content("x" * (1024 * 1024 + 1) + tail)
    deliver([alice.address], message.as_bytes())
    item = Message.objects.get()
    client.force_login(alice)
    response = client.get(f"/messages/{item.pk}/")
    assert b'TAIL &lt;img src=' in response.content
    assert b"https://example.org/path" in response.content
    assert b"truncated" not in response.content
    html_only = EmailMessage()
    html_only.set_content('<h1>All text</h1><a href="https://example.org">Link</a>', subtype="html")
    deliver([alice.address], html_only.as_bytes())
    response = client.get(f"/messages/{Message.objects.latest('pk').pk}/")
    assert b"no plain-text part" in response.content
    assert b"&lt;h1&gt;All text&lt;/h1&gt;" in response.content
    assert b"<iframe" not in response.content


def test_embedded_images_links_and_formatting():
    message = EmailMessage()
    message.set_content('''<style>p { color: red; }</style><p style="font-size:24px">Body</p>
<img src="cid:picture%40mail"><a href="https://example.org/?a=1&amp;b=2" target="_top" ping="https://example.invalid">Link</a>
<meta http-equiv="refresh" content="0;url=https://example.invalid"><base href="https://example.invalid">''', subtype="html")
    message.add_related(b"image bytes", maintype="image", subtype="png", cid="<picture@mail>")
    html = full_html(parse(message.as_bytes()))
    assert 'src="data:image/png;base64,aW1hZ2UgYnl0ZXM="' in html
    assert '<style>p { color: red; }</style>' in html
    assert 'style="font-size:24px"' in html
    assert 'href="https://example.org/?a=1&amp;b=2"' in html
    assert 'target="_blank" rel="noopener noreferrer"' in html
    assert '_top' not in html and 'ping=' not in html and 'http-equiv' not in html and '<base' not in html


def test_full_html_policy_and_ownership(client, alice, bob, raw):
    deliver([alice.address], raw)
    item = Message.objects.get()
    path = f"/messages/{item.pk}/html/"
    assert client.get(path).status_code == 302
    client.force_login(bob)
    assert client.get(path).status_code == 404
    assert client.post(f"/messages/{item.pk}/", {"view": "full"}).status_code == 404
    client.force_login(alice)
    response = client.get(path)
    policy = response["Content-Security-Policy"]
    assert "default-src 'none'" in policy and "form-action 'none'" in policy
    assert "img-src https: http: data:" in policy
    assert "style-src 'unsafe-inline' https: http:" in policy
    for permission in ["allow-scripts", "allow-same-origin", "allow-forms", "allow-top-navigation"]:
        assert permission not in policy
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["X-Frame-Options"] == "SAMEORIGIN"
