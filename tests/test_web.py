import io
import tarfile
from unittest.mock import patch

import pytest
from django.contrib.auth.forms import PasswordChangeForm
from django.test import Client
from django.urls import reverse

from mailserver.models import Account, Message
from mailserver.storage import deliver

pytestmark = pytest.mark.django_db


def test_login_logout_and_security_headers(client, alice):
    assert client.get("/").status_code == 302
    response = client.post("/login/", {"username": alice.address.upper(), "password": "Alice-passphrase-123!"})
    assert response.status_code == 302
    response = client.get("/")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert "default-src 'none'" in response["Content-Security-Policy"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin"
    assert client.get("/logout/").status_code == 405
    assert client.post("/logout/").status_code == 302
    assert client.get("/").status_code == 302


def test_csrf_required(alice):
    client = Client(enforce_csrf_checks=True)
    assert client.post("/login/", {"username": "alice", "password": "Alice-passphrase-123!"}).status_code == 403
    client.force_login(alice)
    assert client.post("/logout/").status_code == 403


def test_login_throttle(client, alice):
    for _ in range(10):
        assert client.post("/login/", {"username": "alice", "password": "wrong"}).status_code == 200
    assert client.post("/login/", {"username": "alice", "password": "Alice-passphrase-123!"}).status_code == 429


def test_user_cannot_admin(client, alice, admin):
    client.force_login(alice)
    for path in ["/admin/", "/admin/create/", "/admin/export/", f"/admin/accounts/{admin.id}/", f"/admin/accounts/{admin.id}/delete/", f"/admin/accounts/{admin.id}/reset/"]:
        assert client.get(path).status_code == 403
        assert client.post(path, {"confirm": "on"}).status_code == 403


def test_mail_isolation_includes_admin(client, alice, bob, admin, raw):
    deliver([alice.address], raw)
    item = Message.objects.get()
    for account in [bob, admin]:
        client.force_login(account)
        for path in [f"/messages/{item.id}/", f"/messages/{item.id}/html/", f"/messages/{item.id}/attachments/4/", f"/messages/{item.id}/delete/"]:
            assert client.get(path).status_code == 404
        assert client.post(f"/messages/{item.id}/read/", {"read": "yes"}).status_code == 404
        assert client.post(f"/messages/{item.id}/delete/", {"confirm": "on"}).status_code == 404


def test_read_html_attachment_and_delete(client, alice, raw):
    deliver([alice.address], raw)
    item = Message.objects.get()
    client.force_login(alice)
    response = client.get(reverse("message", args=[item.id]))
    assert b"&lt;script&gt;not markup&lt;/script&gt;" in response.content
    assert b"sandbox" in response.content
    response = client.get(reverse("message_html", args=[item.id]))
    for forbidden in [b"<script", b"<img", b"<form", b"tracker.invalid", b"<style"]:
        assert forbidden not in response.content
    assert response.content.count(b"href=") == 1
    assert b'href="/assets/message.css"' in response.content
    assert "sandbox" in response["Content-Security-Policy"]
    assert "script-src" not in response["Content-Security-Policy"]
    assert "default-src 'none'" in response["Content-Security-Policy"]
    from mailserver.mime import attachments, parse
    index = attachments(parse(raw))[0][0]
    response = client.get(reverse("attachment", args=[item.id, index]))
    assert response.content == b"attachment bytes\x00\xff"
    assert response["Content-Type"] == "application/octet-stream"
    assert "report.bin" in response["Content-Disposition"]
    assert "../" not in response["Content-Disposition"]
    assert client.post(reverse("read_state", args=[item.id]), {"read": "yes"}).status_code == 302
    item.refresh_from_db()
    assert item.is_read
    client.post(reverse("read_state", args=[item.id]), {"read": "no"})
    item.refresh_from_db()
    assert not item.is_read
    client.get(reverse("delete_message", args=[item.id]))
    client.post(reverse("delete_message", args=[item.id]))
    assert Message.objects.exists()
    client.post(reverse("delete_message", args=[item.id]), {"confirm": "on"})
    assert not Message.objects.exists()


def test_admin_create_edit_delete_and_export(client, admin, alice, raw):
    client.force_login(admin)
    assert b"Disk used:" in client.get("/admin/").content
    response = client.post("/admin/create/", {"username": "new-user", "role": "USER", "quota_mib": 2, "password": "Temporary-passphrase-123!"})
    assert response.status_code == 302
    user = Account.objects.get(username="new-user")
    assert user.must_change_password and user.quota_bytes == 2 * 1024**2
    client.post(reverse("edit_account", args=[user.id]), {"username": "renamed", "role": "ADMIN", "quota_mib": 3})
    user.refresh_from_db()
    assert user.username == "new-user" and user.role == "ADMIN"
    deliver([alice.address, user.address], raw)
    response = client.post("/admin/export/", {"confirm": "on"})
    with tarfile.open(fileobj=io.BytesIO(b"".join(response.streaming_content))) as tar:
        assert len([entry for entry in tar if entry.isfile()]) == 2
    client.post(reverse("delete_account", args=[user.id]), {"confirm": "on"})
    assert not Account.objects.filter(pk=user.id).exists()
    assert Message.objects.count() == 1


def test_final_admin_cannot_be_removed(client, admin):
    client.force_login(admin)
    response = client.post(reverse("delete_account", args=[admin.id]), {"confirm": "on"})
    assert b"Cannot delete the final" in response.content
    response = client.post(reverse("edit_account", args=[admin.id]), {"role": "USER", "quota_mib": 5})
    assert b"Cannot demote the final" in response.content
    admin.refresh_from_db()
    assert admin.role == "ADMIN"


def test_password_reset_revokes_sessions_and_forces_change(client, admin, alice):
    user_client = Client()
    user_client.force_login(alice)
    client.force_login(admin)
    client.post(reverse("reset_password", args=[alice.id]), {"password": "Temporary-passphrase-123!"})
    assert user_client.get("/").status_code == 302
    response = user_client.post("/login/", {"username": "alice", "password": "Temporary-passphrase-123!"})
    assert response.url == "/password/"
    assert user_client.get("/").url == "/password/"
    response = user_client.post("/password/", {"old_password": "Temporary-passphrase-123!", "new_password1": "Changed-passphrase-456!", "new_password2": "Changed-passphrase-456!"})
    assert response.status_code == 302
    alice.refresh_from_db()
    assert not alice.must_change_password
    assert user_client.get("/").status_code == 200


def test_role_change_takes_effect_immediately(client, admin):
    other = Account.objects.create_user("second", "Different-passphrase-123!", role="ADMIN")
    second_client = Client()
    second_client.force_login(other)
    client.force_login(admin)
    client.post(reverse("edit_account", args=[other.id]), {"role": "USER", "quota_mib": 1})
    assert second_client.get("/admin/").status_code == 403


def test_password_is_hashed(alice, settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
    alice.set_password("Hash-check-passphrase-123!")
    alice.save()
    assert alice.password.startswith("pbkdf2_sha256$")
    assert alice.check_password("Hash-check-passphrase-123!")


def test_invalid_and_duplicate_accounts(client, admin, alice):
    client.force_login(admin)
    for username, password in [("alice", "Another-passphrase-123!"), ("a..b", "Another-passphrase-123!"), ("weak", "password")]:
        response = client.post("/admin/create/", {"username": username, "role": "USER", "quota_mib": 1024, "password": password})
        assert response.status_code == 200
    assert Account.objects.count() == 2


def test_invalid_host_rejected(client):
    assert client.get("/login/", HTTP_HOST="evil.invalid").status_code == 400


def test_password_change_does_not_undo_concurrent_demotion(client, admin):
    client.force_login(admin)
    original = PasswordChangeForm.save

    def demote_then_save(form, commit=True):
        Account.objects.filter(pk=admin.pk).update(role="USER")
        return original(form, commit=commit)

    with patch.object(PasswordChangeForm, "save", demote_then_save):
        response = client.post("/password/", {"old_password": "Admin-passphrase-123!", "new_password1": "Changed-passphrase-456!", "new_password2": "Changed-passphrase-456!"})
    assert response.status_code == 302
    admin.refresh_from_db()
    assert admin.role == "USER"
    assert admin.check_password("Changed-passphrase-456!")
