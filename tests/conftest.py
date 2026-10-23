from email.message import EmailMessage
from email.policy import SMTP

import pytest
from django.conf import settings

from mailserver.models import Account


@pytest.fixture(autouse=True)
def config(settings, tmp_path):
    settings.DATA_DIR = tmp_path
    settings.DISK_RESERVE_BYTES = 0
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def admin(db):
    return Account.objects.create_user("admin", "Admin-passphrase-123!", role="ADMIN")


@pytest.fixture
def alice(db):
    return Account.objects.create_user("alice", "Alice-passphrase-123!")


@pytest.fixture
def bob(db):
    return Account.objects.create_user("bob", "Bob-passphrase-123!")


@pytest.fixture
def raw():
    message = EmailMessage()
    message["From"] = "Sender <sender@example.org>"
    message["To"] = f"alice@{settings.MAIL_DOMAIN}"
    message["Subject"] = "Test message — unicode"
    message.set_content("Plain body <script>not markup</script>")
    message.add_alternative('<h1>HTML body</h1><script>parent.hacked=1</script><img src="https://tracker.invalid/pixel"><a href="javascript:alert(1)">danger</a><form action="https://tracker.invalid"><input></form><style>body{background:url(https://tracker.invalid)}</style>', subtype="html")
    message.add_attachment(b"attachment bytes\x00\xff", maintype="application", subtype="octet-stream", filename="../../report.bin")
    return message.as_bytes(policy=SMTP)
