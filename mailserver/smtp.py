import asyncio
import logging
import signal
import ssl
import time
from collections import Counter

from aiosmtpd.smtp import SMTP
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections

from .storage import DeliveryRejected, deliver, recipient, used_bytes

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self):
        self.entries = {}

    def allow(self, key, limit, seconds=3600):
        now = time.monotonic()
        self.entries = {k: v for k, v in self.entries.items() if v[0] + seconds > now}
        if key not in self.entries:
            if len(self.entries) >= 4096:
                return False
            self.entries[key] = (now, 0)
        started, count = self.entries[key]
        self.entries[key] = (started, count + 1)
        return count < limit


def check_recipient(address):
    close_old_connections()
    account = recipient(address)
    if account is None:
        return "550 5.1.1 Unknown local recipient; relay denied"
    if used_bytes(account) >= account.quota_bytes:
        return "452 4.2.2 Mailbox quota reached; retry later"
    return "250 2.1.5 Recipient accepted"


def store(addresses, raw):
    close_old_connections()
    deliver(addresses, raw)


class Handler:
    def __init__(self):
        self.rate = RateLimiter()
        self.connections = Counter()
        self.receiving = False

    async def handle_EHLO(self, server, session, envelope, hostname, responses):
        session.host_name = hostname
        return [line for line in responses if not line.startswith("250-AUTH")]

    async def handle_MAIL(self, server, session, envelope, address, mail_options):
        if not self.rate.allow(session.peer[0], settings.SMTP_MESSAGES_PER_HOUR) or not self.rate.allow("global", int(settings.CONFIG.get("smtp_messages_global_hour", 1000))):
            return "451 4.7.0 Delivery rate limit reached; retry later"
        envelope.mail_from = address
        envelope.mail_options.extend(mail_options)
        return "250 2.1.0 Sender accepted"

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if len(envelope.rcpt_tos) >= settings.SMTP_RECIPIENTS:
            return "452 4.5.3 Too many recipients"
        status = await sync_to_async(check_recipient)(address)
        if status.startswith("250") and address.lower() not in envelope.rcpt_tos:
            envelope.rcpt_tos.append(address.lower())
        return status

    async def handle_DATA(self, server, session, envelope):
        try:
            await sync_to_async(store)(envelope.rcpt_tos, envelope.original_content)
        except DeliveryRejected as error:
            return str(error)
        return "250 2.0.0 Message stored"

    async def handle_exception(self, error):
        logger.error("SMTP failure before acceptance: %s", type(error).__name__)
        return "451 4.3.0 Local processing failed; retry later"


class InboundSMTP(SMTP):
    def __init__(self, handler, **kwargs):
        self.admitted = False
        self.peer_ip = None
        super().__init__(handler, **kwargs)

    def connection_made(self, transport):
        handler = self.event_handler
        if not self.admitted:
            self.peer_ip = transport.get_extra_info("peername")[0]
            if sum(handler.connections.values()) >= settings.SMTP_CONNECTIONS or handler.connections[self.peer_ip] >= 4:
                transport.write(b"421 4.3.2 Connection limit reached\r\n")
                transport.close()
                return
            self.admitted = True
            handler.connections[self.peer_ip] += 1
        super().connection_made(transport)

    def connection_lost(self, error):
        if self.admitted:
            self.event_handler.connections[self.peer_ip] -= 1
            if not self.event_handler.connections[self.peer_ip]:
                del self.event_handler.connections[self.peer_ip]
            self.admitted = False
            super().connection_lost(error)

    def eof_received(self):
        if self.admitted:
            return super().eof_received()
        return False

    async def smtp_AUTH(self, arg):
        await self.push("502 5.5.1 Authentication is not available")

    async def smtp_VRFY(self, arg):
        await self.push("252 2.5.2 Verification is not available")

    async def smtp_DATA(self, arg):
        if self.event_handler.receiving:
            await self.push("452 4.3.1 Another delivery is in progress; retry later")
            return
        self.event_handler.receiving = True
        try:
            await super().smtp_DATA(arg)
        finally:
            self.event_handler.receiving = False


def factory(handler, tls_context=None):
    return InboundSMTP(handler, hostname=settings.MAIL_DOMAIN, ident="Inbound", data_size_limit=settings.MAX_MESSAGE_BYTES,
                       enable_SMTPUTF8=False, decode_data=False, tls_context=tls_context,
                       require_starttls=False, auth_exclude_mechanism=["LOGIN", "PLAIN"],
                       command_call_limit=200, timeout=120)


async def serve():
    context = None
    if settings.TLS_CERT and settings.TLS_KEY:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(settings.TLS_CERT, settings.TLS_KEY)
    elif not settings.DEVELOPMENT:
        raise RuntimeError("Production SMTP requires a certificate and private key for STARTTLS")
    handler = Handler()
    loop = asyncio.get_running_loop()
    server = await loop.create_server(lambda: factory(handler, context), settings.SMTP_HOST, settings.SMTP_PORT)
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    logger.info("Inbound SMTP listening on %s:%d", settings.SMTP_HOST, settings.SMTP_PORT)
    async with server:
        await stop.wait()
