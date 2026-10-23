import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from mailserver.models import Message
from mailserver.storage import deliver

pytestmark = pytest.mark.django_db


def test_updates_require_login(client):
    response = client.get("/inbox/updates/")
    assert response.status_code == 302
    assert response.url.startswith("/login/")


def test_updates_are_read_only_and_no_store(client, alice):
    client.force_login(alice)
    response = client.get("/inbox/updates/")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert b"data-inbox-content" in response.content
    assert b"No messages yet" in response.content
    assert b"<html" not in response.content
    assert client.post("/inbox/updates/").status_code == 405


def test_deliveries_appear_without_loading_bodies(client, alice, raw):
    client.force_login(alice)
    before = client.get("/inbox/updates/")
    assert b"No messages yet" in before.content
    deliver([alice.address], raw)
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/inbox/updates/")
    assert "Test message — unicode" in response.content.decode()
    assert b"<strong>1</strong><span>Unread</span>" in response.content
    assert b"Plain body" not in response.content
    assert all('"raw"' not in query["sql"] for query in queries)
    assert Message.objects.get().is_read is False


def test_updates_keep_mailboxes_isolated(client, alice, bob, admin, raw):
    deliver([alice.address], raw)
    for account in (bob, admin):
        client.force_login(account)
        response = client.get("/inbox/updates/", {"account": alice.pk})
        assert b"No messages yet" in response.content
        assert b"Test message" not in response.content
        assert f'data-account="{account.pk}:{account.role}"'.encode() in response.content


def test_updates_preserve_pagination(client, alice):
    Message.objects.bulk_create([
        Message(account=alice, raw=b"test", size=4, subject=f"Item {number}")
        for number in range(53)
    ])
    client.force_login(alice)
    response = client.get("/inbox/updates/?page=2")
    assert response.context["page"].number == 2
    assert len(response.context["page"]) == 3
    assert b"Item 0<" in response.content
    assert b"Item 52<" not in response.content
    assert b"Page 2 of 2" in response.content
    assert client.get("/inbox/updates/?page=999").context["page"].number == 2
    assert client.get("/inbox/updates/?page=invalid").context["page"].number == 1


def test_updates_reflect_read_state_and_deletion(client, alice, raw):
    deliver([alice.address], raw)
    item = Message.objects.get()
    client.force_login(alice)
    item.is_read = True
    item.save(update_fields=["is_read"])
    assert b"<strong>0</strong><span>Unread</span>" in client.get("/inbox/updates/").content
    item.delete()
    assert b"No messages yet" in client.get("/inbox/updates/").content


def test_password_change_gate_applies_to_polling(client, alice):
    alice.must_change_password = True
    alice.save(update_fields=["must_change_password"])
    client.force_login(alice)
    response = client.get("/inbox/updates/")
    assert response.status_code == 302 and response.url == "/password/"


def test_subjects_are_escaped_in_updates(client, alice):
    Message.objects.create(account=alice, raw=b"test", size=4, subject='<img src=x onerror="alert(1)">', sender="<script>alert(1)</script>")
    client.force_login(alice)
    response = client.get("/inbox/updates/")
    assert b"<img" not in response.content and b"<script" not in response.content
    assert b"&lt;img" in response.content


def test_dark_theme_and_inbox_script_scope(client, alice):
    response = client.get("/login/")
    assert b'name="color-scheme" content="dark"' in response.content
    assert b"/assets/inbox.js" not in response.content
    client.force_login(alice)
    response = client.get("/")
    assert b'<script src="/assets/inbox.js" defer></script>' in response.content
    assert b"Enable JavaScript for automatic updates" in response.content
    assert "script-src 'self'" in response["Content-Security-Policy"]
    assert "connect-src 'self'" in response["Content-Security-Policy"]


@pytest.mark.parametrize("path,content_type", [
    ("/assets/style.css", "text/css"),
    ("/assets/message.css", "text/css"),
    ("/assets/inbox.js", "text/javascript"),
    ("/assets/select.js", "text/javascript"),
])
def test_assets_are_available(client, path, content_type):
    response = client.get(path)
    assert response.status_code == 200
    assert response["Content-Type"] == content_type
    assert b"".join(response.streaming_content)
