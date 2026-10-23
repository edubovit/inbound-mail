import smtplib
import socket
from unittest.mock import patch

import pytest
from aiosmtpd.controller import Controller
from django.db import OperationalError

from mailserver.models import Message
from mailserver.smtp import Handler, RateLimiter, factory

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def smtp_server():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    class Server(Controller):
        def factory(self):
            return factory(self.handler)

    controller = Server(Handler(), hostname="127.0.0.1", port=port)
    controller.start()
    yield port
    controller.stop()


def test_real_smtp_delivery(smtp_server, alice, raw):
    with smtplib.SMTP("127.0.0.1", smtp_server, timeout=5) as client:
        client.ehlo()
        assert "auth" not in client.esmtp_features
        assert client.docmd("AUTH", "PLAIN anything")[0] == 502
        assert client.verify(alice.address)[0] == 252
        assert client.sendmail("sender@example.org", alice.address, raw) == {}
    assert bytes(Message.objects.get().raw) == raw


def test_relay_unknown_and_no_aliases(smtp_server, alice):
    with smtplib.SMTP("127.0.0.1", smtp_server, timeout=5) as client:
        client.ehlo()
        client.mail("sender@example.org")
        for address in ["someone@external.test", "unknown@mail.test", "alice+tag@mail.test"]:
            assert client.rcpt(address)[0] == 550
    assert not Message.objects.exists()


def test_smtp_declared_and_actual_size(smtp_server, alice, settings):
    settings.MAX_MESSAGE_BYTES = 100
    with smtplib.SMTP("127.0.0.1", smtp_server, timeout=5) as client:
        client.ehlo()
        assert client.mail("a@example.org", options=["SIZE=101"])[0] == 552
        assert client.mail("a@example.org")[0] == 250
        assert client.rcpt(alice.address)[0] == 250
        assert client.data(b"Subject: large\r\n\r\n" + b"x" * 150)[0] == 552
    assert not Message.objects.exists()


def test_smtp_storage_failure_is_temporary(smtp_server, alice, raw):
    with patch("mailserver.smtp.deliver", side_effect=OperationalError("test")):
        with smtplib.SMTP("127.0.0.1", smtp_server, timeout=5) as client:
            with pytest.raises(smtplib.SMTPDataError) as error:
                client.sendmail("sender@example.org", alice.address, raw)
            assert error.value.smtp_code == 451
    assert not Message.objects.exists()


def test_smtp_rate_limit(smtp_server, settings):
    settings.SMTP_MESSAGES_PER_HOUR = 1
    with smtplib.SMTP("127.0.0.1", smtp_server, timeout=5) as client:
        client.ehlo()
        assert client.mail("sender@example.org")[0] == 250
        client.rset()
        assert client.mail("sender@example.org")[0] == 451


def test_smtp_busy_is_temporary(smtp_server, alice):
    with smtplib.SMTP("127.0.0.1", smtp_server, timeout=5) as first, smtplib.SMTP("127.0.0.1", smtp_server, timeout=5) as second:
        for client in (first, second):
            client.ehlo()
            client.mail("sender@example.org")
            client.rcpt(alice.address)
        assert first.docmd("DATA")[0] == 354
        assert second.docmd("DATA")[0] == 452
        first.send(b"Subject: done\r\n\r\nbody\r\n.\r\n")
        assert first.getreply()[0] == 250


def test_connection_limit(smtp_server, settings):
    settings.SMTP_CONNECTIONS = 1
    with smtplib.SMTP("127.0.0.1", smtp_server, timeout=5):
        with pytest.raises(smtplib.SMTPConnectError) as error:
            smtplib.SMTP("127.0.0.1", smtp_server, timeout=5)
        assert error.value.smtp_code == 421


def test_rate_expiry():
    limiter = RateLimiter()
    with patch("mailserver.smtp.time.monotonic", return_value=10):
        assert limiter.allow("test", 1)
        assert not limiter.allow("test", 1)
    with patch("mailserver.smtp.time.monotonic", return_value=3611):
        assert limiter.allow("test", 1)


def test_smtp_hostname_does_not_change_recipient_domain(smtp_server, alice, raw, settings):
    settings.SMTP_HOSTNAME = "mx.example.com"
    client = smtplib.SMTP(timeout=5)
    with client:
        code, banner = client.connect("127.0.0.1", smtp_server)
        assert code == 220 and banner.startswith(b"mx.example.com ")
        code, response = client.ehlo()
        assert code == 250 and response.splitlines()[0] == b"mx.example.com"
        client.mail("sender@example.org")
        assert client.rcpt("alice@mx.example.com")[0] == 550
        client.rset()
        assert client.sendmail("sender@example.org", alice.address, raw) == {}
    item = Message.objects.get()
    assert item.account == alice
    assert bytes(item.raw) == raw
