import json
import os
import subprocess
import sys


def test_fresh_schema_durable_delivery_concurrency_and_reinstall_refusal(tmp_path):
    script = r'''
import os, sys
from concurrent.futures import ThreadPoolExecutor
os.environ['DJANGO_SETTINGS_MODULE'] = 'mailserver.settings'
import django
django.setup()
from django.conf import settings
from django.db import connections, connection
from mailserver.cli import initialize
from mailserver.models import Account, Message
from mailserver.storage import deliver, DeliveryRejected
settings.DISK_RESERVE_BYTES = 0
initialize('admin', 'Initial-admin-passphrase-943!')
raw = b'Subject: durable\r\n\r\nOriginal mail\r\n'
user = Account.objects.get(username='admin')
user.quota_bytes = len(raw) * 2
user.save()
def receive(_):
    try:
        deliver(['admin@mail.test'], raw)
        return 'accepted'
    except DeliveryRejected:
        return 'rejected'
    finally:
        connections.close_all()
with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(receive, range(8)))
assert results.count('accepted') == 2, results
assert results.count('rejected') == 6, results
assert Message.objects.count() == 2
with connection.cursor() as cursor:
    cursor.execute('PRAGMA auto_vacuum')
    assert cursor.fetchone()[0] == 1
    cursor.execute('PRAGMA synchronous')
    assert cursor.fetchone()[0] == 3
try:
    initialize('other', 'Different-admin-passphrase-943!')
except SystemExit:
    pass
else:
    raise AssertionError('reinitialization allowed')
connections.close_all()
'''
    env = {**os.environ, "MAIL_DEV_DATA": str(tmp_path / "data")}
    env.pop("MAIL_CONFIG", None)
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    import sqlite3
    with sqlite3.connect(tmp_path / "data" / "mail.sqlite3") as database:
        assert database.execute("select count(*) from mailserver_message").fetchone()[0] == 2
        assert database.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_production_root_gate_on_windows_or_unprivileged(tmp_path):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"data_dir": str(tmp_path), "secret_key": "not-a-real-secret"}))
    result = subprocess.run([sys.executable, "-m", "mailserver.cli", "--config", str(config), "export", "-"], capture_output=True, timeout=10)
    assert result.returncode != 0
    assert b"requires root" in result.stderr
