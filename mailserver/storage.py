import io
import logging
import shutil
import tarfile
from email import policy
from email.parser import BytesHeaderParser

from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from .models import Account, Message

logger = logging.getLogger(__name__)


class DeliveryRejected(Exception):
    pass


def recipient(address):
    local, separator, domain = address.lower().rpartition("@")
    if not separator or domain != settings.MAIL_DOMAIN:
        return None
    return Account.objects.filter(username=local).first()


def used_bytes(account):
    return account.mail.aggregate(total=Sum("size"))["total"] or 0


def deliver(addresses, raw):
    size = len(raw)
    if size > settings.MAX_MESSAGE_BYTES:
        raise DeliveryRejected("552 5.3.4 Message exceeds size limit")
    headers = BytesHeaderParser(policy=policy.default).parsebytes(raw[:65536])
    sender = str(headers.get("From", ""))[:512]
    subject = str(headers.get("Subject", ""))[:512]
    with transaction.atomic():
        accounts = [recipient(address) for address in sorted({a.lower() for a in addresses})]
        if not accounts or any(account is None for account in accounts):
            raise DeliveryRejected("550 5.1.1 Recipient no longer exists")
        needed = size * len(accounts)
        if shutil.disk_usage(settings.DATA_DIR).free < settings.DISK_RESERVE_BYTES + needed * 3 + 1024**2:
            raise DeliveryRejected("452 4.3.1 Server disk reserve reached; retry later")
        for account in accounts:
            if used_bytes(account) + size > account.quota_bytes:
                raise DeliveryRejected("452 4.2.2 Mailbox quota reached; retry later")
        for account in accounts:
            Message.objects.create(account=account, raw=raw, size=size, sender=sender, subject=subject)
    logger.info("Accepted message: bytes=%d recipients=%d", size, len(accounts))


def export_mail():
    accounts = list(Account.objects.order_by("id").values_list("id", "username"))
    cutoff = Message.objects.order_by("-id").values_list("id", flat=True).first() or 0
    for account_id, username in accounts:
        folder = tarfile.TarInfo(f"{username}/")
        folder.type = tarfile.DIRTYPE
        folder.mode = 0o700
        yield folder.tobuf(format=tarfile.PAX_FORMAT)
        last = 0
        while True:
            message = Message.objects.filter(account_id=account_id, id__gt=last, id__lte=cutoff).order_by("id").only("id", "raw", "size", "received_at").first()
            if message is None:
                break
            last = message.id
            entry = tarfile.TarInfo(f"{username}/{message.id}.eml")
            entry.size = message.size
            entry.mode = 0o600
            entry.mtime = int(message.received_at.timestamp())
            yield entry.tobuf(format=tarfile.PAX_FORMAT)
            source = io.BytesIO(bytes(message.raw))
            while chunk := source.read(65536):
                yield chunk
            yield b"\0" * (-entry.size % 512)
    yield b"\0" * 1024
