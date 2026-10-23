import io
import tarfile
from collections import namedtuple
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import OperationalError

from mailserver.models import Account, Message
from mailserver.storage import (
    DeliveryRejected,
    deliver,
    export_mail,
    recipient,
    used_bytes,
)

pytestmark = pytest.mark.django_db


def test_delivery_preserves_original_and_deduplicates(alice, raw):
    deliver([alice.address, alice.address.upper()], raw)
    item = Message.objects.get()
    assert bytes(item.raw) == raw
    assert item.subject == "Test message — unicode"
    assert item.size == used_bytes(alice) == len(raw)
    assert recipient(alice.address.upper()) == alice
    assert recipient("alice@elsewhere.test") is None
    assert recipient("missing@mail.test") is None


def test_all_recipients_atomic_on_quota(alice, bob, raw):
    bob.quota_bytes = 1
    bob.save()
    with pytest.raises(DeliveryRejected, match="452"):
        deliver([alice.address, bob.address], raw)
    assert not Message.objects.exists()


def test_quota_and_delete_releases_usage(alice, raw):
    alice.quota_bytes = len(raw)
    alice.save()
    deliver([alice.address], raw)
    with pytest.raises(DeliveryRejected, match="quota"):
        deliver([alice.address], raw)
    Message.objects.all().delete()
    deliver([alice.address], raw)
    assert Message.objects.count() == 1


def test_disk_reserve(alice, raw, settings):
    settings.DISK_RESERVE_BYTES = 1024
    disk = namedtuple("Disk", "total used free")(10000, 9000, 1000)
    with patch("mailserver.storage.shutil.disk_usage", return_value=disk), pytest.raises(DeliveryRejected, match="reserve"):
        deliver([alice.address], raw)
    assert not Message.objects.exists()


def test_oversize(alice, raw, settings):
    settings.MAX_MESSAGE_BYTES = len(raw) - 1
    with pytest.raises(DeliveryRejected, match="552"):
        deliver([alice.address], raw)
    assert not Message.objects.exists()


def test_deleted_recipient_and_empty_transaction(alice, raw):
    for recipients in ([alice.address, "missing@mail.test"], []):
        with pytest.raises(DeliveryRejected, match="550"):
            deliver(recipients, raw)
    assert not Message.objects.exists()


def test_database_failure_rolls_back(alice, bob, raw):
    original = Message.objects.create
    calls = []

    def failing(**kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OperationalError("simulated disk failure")
        return original(**kwargs)

    with patch("mailserver.storage.Message.objects.create", side_effect=failing), pytest.raises(OperationalError):
        deliver([alice.address, bob.address], raw)
    assert not Message.objects.exists()


def test_export_originals_and_empty_accounts(alice, bob, raw):
    deliver([alice.address], raw)
    archive = io.BytesIO(b"".join(export_mail()))
    with tarfile.open(fileobj=archive) as tar:
        assert "alice" in tar.getnames()
        assert "bob" in tar.getnames()
        files = [entry for entry in tar if entry.isfile()]
        assert len(files) == 1
        assert files[0].name.startswith("alice/")
        assert files[0].name.endswith(".eml")
        assert tar.extractfile(files[0]).read() == raw


def test_export_excludes_new_delivery(alice, raw):
    deliver([alice.address], raw)
    stream = export_mail()
    first = next(stream)
    deliver([alice.address], raw)
    with tarfile.open(fileobj=io.BytesIO(first + b"".join(stream))) as tar:
        assert len([entry for entry in tar if entry.isfile()]) == 1


@pytest.mark.parametrize("username", ["../x", "bad/name", "bad\\name", "a..b", ".start", "end.", "a+b", "x@y", "💥"])
def test_account_names(username):
    with pytest.raises(ValidationError):
        Account.objects.create_user(username, "some-passphrase-123")
