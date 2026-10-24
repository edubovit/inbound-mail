import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.db import IntegrityError

from mailserver import accounts, cli
from mailserver.models import Account, Message


def secret_file(path, value):
    path.write_bytes(value.encode("utf-8"))
    path.chmod(0o600)
    return path


def invoke(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["inbound-mail", "accounts", *map(str, args)])
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_: pytest.fail("Account commands must never prompt"))
    cli.main()
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def credential_accounts(admin, alice):
    for account in (admin, alice):
        hasher = PBKDF2PasswordHasher()
        account.password = hasher.encode("Synthetic-account-password-823!", hasher.salt())
        account.must_change_password = account == alice
        account.save()
    return admin, alice


def test_account_commands_no_prompts_or_secret_output(admin, monkeypatch, capsys, tmp_path):
    password = secret_file(tmp_path / "password", "Script-passphrase-389!\n")
    result = invoke(monkeypatch, capsys, "create", "script-user", "--password-file", password, "--quota-mib", "12")
    assert result["must_change_password"] is True
    user = Account.objects.get(username="script-user")
    assert user.check_password("Script-passphrase-389!")
    assert user.quota_bytes == 12 * 1024**2
    assert "password" not in result
    result = invoke(monkeypatch, capsys, "update", "script-user", "--role", "ADMIN", "--quota-mib", "24", "--no-must-change-password")
    assert result["role"] == "ADMIN" and not result["must_change_password"]
    assert invoke(monkeypatch, capsys, "show", "script-user") == result
    listing = invoke(monkeypatch, capsys, "list")
    assert len(listing) == 2 and all("password" not in row for row in listing)
    old_hash = user.get_session_auth_hash()
    secret_file(password, "Replacement-passphrase-737!\r\n")
    invoke(monkeypatch, capsys, "reset-password", "script-user", "--password-file", password)
    user.refresh_from_db()
    assert user.must_change_password and user.check_password("Replacement-passphrase-737!")
    assert user.get_session_auth_hash() != old_hash
    Message.objects.create(account=user, raw=b"original", size=8)
    assert invoke(monkeypatch, capsys, "delete", "script-user", "--confirm-delete") == {"deleted": "script-user"}
    assert not Message.objects.exists()


@pytest.mark.parametrize("arguments", [
    ("delete", "admin", "--confirm-delete"),
    ("update", "admin", "--role", "USER"),
    ("update", "admin", "--quota-mib", "0"),
    ("update", "missing", "--quota-mib", "10"),
    ("delete", "admin"),
    ("create", "someone"),
])
def test_invalid_operations_do_not_mutate(admin, monkeypatch, capsys, arguments):
    before = list(Account.objects.values())
    with pytest.raises(SystemExit):
        invoke(monkeypatch, capsys, *arguments)
    assert list(Account.objects.values()) == before


def test_duplicate_and_empty_password_rejected(admin, monkeypatch, capsys, tmp_path):
    password = secret_file(tmp_path / "pw", "Another-long-passphrase-123!")
    with pytest.raises(SystemExit):
        invoke(monkeypatch, capsys, "create", "admin", "--password-file", password)
    secret_file(password, "")
    with pytest.raises(SystemExit):
        invoke(monkeypatch, capsys, "create", "other", "--password-file", password)
    assert Account.objects.count() == 1


@pytest.mark.parametrize("content", ["", "line\nline", "bad\x00password", "x" * 4097])
def test_password_file_rejects_invalid_contents(tmp_path, content):
    with pytest.raises(ValueError):
        accounts.read_password(secret_file(tmp_path / "pw", content))


def test_password_spaces_preserved(tmp_path):
    assert accounts.read_password(secret_file(tmp_path / "pw", " spaces are intentional \n")) == " spaces are intentional "


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions and FIFO semantics")
def test_private_file_permissions_links_and_fifo(tmp_path):
    path = secret_file(tmp_path / "pw", "some password")
    path.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        accounts.read_password(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        accounts.read_password(link)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(ValueError, match="regular"):
        accounts.read_password(fifo)


def test_export_import_hashes_settings_no_mail(credential_accounts, tmp_path, settings):
    admin, alice = credential_accounts
    Message.objects.create(account=alice, raw=b"private mail excluded", size=21)
    path = tmp_path / "accounts.json"
    assert accounts.export_accounts(path) == {"exported": 2}
    document = json.loads(path.read_text())
    assert "private mail" not in path.read_text() and "Synthetic-account-password" not in path.read_text()
    assert all(set(row) == accounts.FIELDS for row in document["accounts"])
    assert next(row for row in document["accounts"] if row["username"] == "alice")["password"] == alice.password
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        accounts.export_accounts(path)
    Account.objects.all().delete()
    assert accounts.import_accounts(path) == {"imported": 2}
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
    restored = Account.objects.get(username="alice")
    assert restored.check_password("Synthetic-account-password-823!")
    assert restored.must_change_password and restored.quota_bytes == alice.quota_bytes
    assert restored.password == alice.password
    assert not Message.objects.exists()


@pytest.mark.parametrize("damage", ["version", "domain", "duplicate", "hash", "type", "role", "fields", "collision"])
def test_import_rejects_entire_archive(credential_accounts, tmp_path, damage):
    path = tmp_path / "accounts.json"
    accounts.export_accounts(path)
    data = json.loads(path.read_text())
    if damage == "version":
        data["format"] = "legacy-accounts"
    elif damage == "domain":
        data["domain"] = "different.example"
    elif damage == "duplicate":
        data["accounts"].append(data["accounts"][0])
    elif damage == "hash":
        data["accounts"][-1]["password"] = "not-a-password-hash"
    elif damage == "type":
        data["accounts"][-1]["quota_bytes"] = True
    elif damage == "role":
        data["accounts"][-1]["role"] = "ROOT"
    elif damage == "fields":
        data["accounts"][-1]["messages"] = []
    else:
        data["accounts"][0]["username"] = "new-account"
    secret_file(path, json.dumps(data))
    before = list(Account.objects.values())
    with pytest.raises(ValueError):
        accounts.import_accounts(path)
    assert list(Account.objects.values()) == before


def test_import_rolls_back_database_failure(credential_accounts, tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    accounts.export_accounts(path)
    Account.objects.all().delete()
    save = Account.save
    def failing_save(self, *args, **kwargs):
        if self.username == "alice":
            raise IntegrityError("synthetic failure")
        return save(self, *args, **kwargs)
    monkeypatch.setattr(Account, "save", failing_save)
    with pytest.raises(IntegrityError):
        accounts.import_accounts(path)
    assert not Account.objects.exists()


def test_import_does_not_overwrite_existing_mail(credential_accounts, tmp_path):
    path = tmp_path / "accounts.json"
    accounts.export_accounts(path)
    Account.objects.all().delete()
    existing = Account.objects.create_user("existing", "Existing-passphrase-345!", role="ADMIN")
    message = Message.objects.create(account=existing, raw=b"keep", size=4)
    accounts.import_accounts(path)
    assert Account.objects.count() == 3
    assert Message.objects.get(pk=message.pk).raw == b"keep"


def test_import_empty_database_requires_admin(credential_accounts, tmp_path):
    path = tmp_path / "accounts.json"
    accounts.export_accounts(path)
    data = json.loads(path.read_text())
    data["accounts"] = [row for row in data["accounts"] if row["role"] == "USER"]
    secret_file(path, json.dumps(data))
    Account.objects.all().delete()
    with pytest.raises(ValueError, match="administrator"):
        accounts.import_accounts(path)


def test_cli_production_commands_require_root(tmp_path):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("requires an unprivileged process")
    for command in (["accounts", "list"], ["upgrade", "--check"]):
        result = subprocess.run([sys.executable, "-m", "mailserver.cli", "--config", str(tmp_path / "missing"), *command],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode != 0 and "requires root" in result.stderr


def test_update_keeps_password_and_sessions(admin):
    password = admin.password
    args = SimpleNamespace(account_command="update", username="admin", role=None, quota_mib=42, must_change_password=None)
    accounts.run(args)
    admin.refresh_from_db()
    assert admin.password == password and admin.quota_bytes == 42 * 1024**2


def test_admin_recovery_uses_file_without_prompt(admin, alice, monkeypatch, capsys, tmp_path):
    password = secret_file(tmp_path / "pw", "Recovery-passphrase-683!")
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_: pytest.fail("Recovery must not prompt"))
    monkeypatch.setattr(sys, "argv", ["inbound-mail", "reset-admin", "admin", "--password-file", str(password)])
    cli.main()
    assert json.loads(capsys.readouterr().out)["must_change_password"]
    admin.refresh_from_db()
    assert admin.check_password("Recovery-passphrase-683!")
    monkeypatch.setattr(sys, "argv", ["inbound-mail", "reset-admin", "alice", "--password-file", str(password)])
    with pytest.raises(SystemExit, match="No administrator"):
        cli.main()
    alice.refresh_from_db()
    assert alice.check_password("Alice-passphrase-123!")


def test_real_cli_subprocess_archive_round_trip(tmp_path):
    env = {**os.environ, "MAIL_DEV_DATA": str(tmp_path / "original")}
    env.pop("MAIL_CONFIG", None)
    def process(*arguments):
        return subprocess.run([sys.executable, "-m", "mailserver.cli", *map(str, arguments)],
                              env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    def initialize(username):
        script = f"from mailserver.cli import setup,initialize; setup(); initialize({username!r},'Synthetic-bootstrap-passphrase-847!')"
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    initialize("original-admin")
    password = secret_file(tmp_path / "pw", "Synthetic-provisioned-passphrase-958!\n")
    result = process("accounts", "create", "provisioned", "--password-file", password, "--no-must-change-password")
    assert result.returncode == 0 and not json.loads(result.stdout)["must_change_password"], result.stderr
    archive = tmp_path / "archive.json"
    assert process("accounts", "export", archive).returncode == 0
    assert process("accounts", "import", archive).returncode != 0
    env["MAIL_DEV_DATA"] = str(tmp_path / "destination")
    initialize("temporary-admin")
    result = process("accounts", "import", archive)
    assert result.returncode == 0 and json.loads(result.stdout) == {"imported": 2}, result.stderr
    assert process("accounts", "delete", "temporary-admin", "--confirm-delete").returncode == 0
    result = process("accounts", "list")
    assert result.returncode == 0
    assert {row["username"] for row in json.loads(result.stdout)} == {"original-admin", "provisioned"}
    assert "pbkdf2" not in result.stdout and "Synthetic-provisioned" not in result.stdout
