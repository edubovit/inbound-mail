import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mailserver import cli, upgrade


@pytest.fixture
def layout(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    (app / "old-code").write_text("original")
    config = tmp_path / "config" / "config.json"
    config.parent.mkdir()
    config.write_text('{"secret_key":"synthetic-secret"}')
    backup = tmp_path / "backup"
    backup.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    with sqlite3.connect(data / "mail.sqlite3") as database:
        database.execute("CREATE TABLE evidence (value TEXT)")
        database.execute("INSERT INTO evidence VALUES ('existing mail')")
    monkeypatch.setattr(upgrade, "APP", app)
    monkeypatch.setattr(upgrade, "CONFIG", config)
    monkeypatch.setattr(upgrade, "BACKUPS", tmp_path / "backups")
    monkeypatch.setattr(upgrade.time, "sleep", lambda *_: None)
    calls = []
    def command(*args, **kwargs):
        calls.append(tuple(map(str, args)))
        if args[:2] == ("systemctl", "show"):
            return "inactive\n"
    monkeypatch.setattr(upgrade, "command", command)
    def snapshot(destination, _):
        shutil.copytree(app, destination / "app")
        shutil.copy2(data / "mail.sqlite3", destination / "mail.sqlite3")
    monkeypatch.setattr(upgrade, "snapshot", snapshot)
    return SimpleNamespace(app=app, config=config, backup=backup, data=data,
                           calls=calls, options={"data_dir": str(data), "disk_reserve_mib": 0})


def test_upgrade_success_preserves_data_and_only_restarts_owned_services(layout, monkeypatch):
    def activate(*_):
        (layout.app / "old-code").unlink()
        (layout.app / "new-code").write_text("candidate")
    monkeypatch.setattr(upgrade, "activate", activate)
    monkeypatch.setattr(upgrade, "verify", lambda _: None)
    before = (layout.data / "mail.sqlite3").read_bytes()
    upgrade.apply(None, None, None, layout.backup, layout.options)
    assert (layout.app / "new-code").read_text() == "candidate"
    assert (layout.backup / "app/old-code").read_text() == "original"
    assert (layout.data / "mail.sqlite3").read_bytes() == before
    assert layout.calls == [("systemctl", "stop", *upgrade.SERVICES),
                            *( ("systemctl", "show", service, "--property=ActiveState", "--value") for service in upgrade.SERVICES),
                            ("systemctl", "start", *upgrade.SERVICES)]


@pytest.mark.parametrize("failure", ["snapshot", "install", "health"])
def test_upgrade_failure_restores_code_not_new_mail(layout, monkeypatch, failure):
    def activate(*_):
        (layout.app / "old-code").unlink()
        (layout.app / "new-code").write_text("partial")
        if failure == "install":
            raise ValueError("install failed")
    def verify(_):
        with sqlite3.connect(layout.data / "mail.sqlite3") as database:
            database.execute("INSERT INTO evidence VALUES ('mail accepted after restart')")
        raise ValueError("health failed")
    monkeypatch.setattr(upgrade, "activate", activate)
    monkeypatch.setattr(upgrade, "verify", verify)
    if failure == "snapshot":
        def broken_snapshot(*_):
            raise OSError("no disk space")
        monkeypatch.setattr(upgrade, "snapshot", broken_snapshot)
    with pytest.raises((ValueError, OSError)):
        upgrade.apply(None, None, None, layout.backup, layout.options)
    assert (layout.app / "old-code").read_text() == "original"
    assert not (layout.app / "new-code").exists()
    assert layout.calls[-1] == ("systemctl", "start", *upgrade.SERVICES)
    with sqlite3.connect(layout.data / "mail.sqlite3") as database:
        rows = database.execute("SELECT value FROM evidence").fetchall()
    assert rows[0] == ("existing mail",)
    if failure == "health":
        assert len(rows) == 2


def test_upgrade_stopping_failure_never_replaces_app(layout, monkeypatch):
    calls = []
    def command(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, "systemctl stop")
    monkeypatch.setattr(upgrade, "command", command)
    monkeypatch.setattr(upgrade, "activate", lambda *_: pytest.fail("must not install"))
    with pytest.raises(subprocess.CalledProcessError):
        upgrade.apply(None, None, None, layout.backup, layout.options)
    assert (layout.app / "old-code").exists()
    assert calls[-1] == ("systemctl", "start", *upgrade.SERVICES)


def test_candidate_preparation_failure_has_no_service_effect(layout, monkeypatch, tmp_path):
    monkeypatch.setattr(upgrade, "preflight", lambda: layout.options)
    monkeypatch.setattr(upgrade, "get_source", lambda *_: tmp_path)
    def fail(*_):
        raise ValueError("incompatible schema")
    monkeypatch.setattr(upgrade, "prepare", fail)
    with pytest.raises(ValueError, match="schema"):
        upgrade.run(SimpleNamespace(source=None, revision=None, check=False))
    assert layout.calls == []
    assert (layout.app / "old-code").exists()


def test_check_only_and_low_disk_never_apply(layout, monkeypatch, tmp_path):
    monkeypatch.setattr(upgrade, "preflight", lambda: layout.options)
    monkeypatch.setattr(upgrade, "get_source", lambda *_: tmp_path)
    monkeypatch.setattr(upgrade, "prepare", lambda *_: (None, None, None))
    monkeypatch.setattr(upgrade, "BACKUPS", tmp_path / "backups")
    monkeypatch.setattr(upgrade, "apply", lambda *_: pytest.fail("must not install"))
    args = SimpleNamespace(source=None, revision=None, check=True)
    upgrade.run(args)
    assert layout.calls == []
    monkeypatch.setattr(upgrade.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    args.check = False
    with pytest.raises(ValueError, match="free disk"):
        upgrade.run(args)


def test_deployment_contract_must_match(tmp_path):
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy/upgrade.json").write_text('{"upgrade":2}')
    with pytest.raises(ValueError, match="contract"):
        upgrade.prepare(tmp_path, tmp_path)


def test_source_download_pins_revision_and_rejects_invalid_sha(tmp_path, monkeypatch):
    sha = "a" * 40
    calls = []
    def download(url, output):
        calls.append(url)
        if output.name == "commit.json":
            output.write_text(json.dumps({"sha": sha}))
        else:
            import tarfile
            with tarfile.open(output, "w:gz"):
                pass
    monkeypatch.setattr(upgrade, "download", download)
    assert upgrade.get_source(tmp_path, None, None).name == f"inbound-mail-{sha}"
    assert calls[-1].endswith("/" + sha)
    with pytest.raises(ValueError, match="commit"):
        upgrade.get_source(tmp_path, None, "master")


def test_source_archive_rejects_links(tmp_path, monkeypatch):
    import tarfile
    def download(_, output):
        with tarfile.open(output, "w:gz") as archive:
            item = tarfile.TarInfo("link")
            item.type = tarfile.SYMTYPE
            item.linkname = "/etc"
            archive.addfile(item)
    monkeypatch.setattr(upgrade, "download", download)
    with pytest.raises(ValueError, match="links"):
        upgrade.get_source(tmp_path, None, "a" * 40)


def test_schema_is_checked_against_actual_fresh_models(tmp_path):
    env = {**os.environ, "MAIL_DEV_DATA": str(tmp_path / "data")}
    env.pop("MAIL_CONFIG", None)
    initialize = "from mailserver.cli import setup, initialize; setup(); initialize('admin', 'Initial-test-passphrase-924!')"
    result = subprocess.run([sys.executable, "-c", initialize], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    check = """
from unittest.mock import patch
from mailserver.cli import setup
setup()
from mailserver.upgrade import check_candidate
with patch('mailserver.upgrade.ssl.SSLContext'):
    check_candidate()
"""
    result = subprocess.run([sys.executable, "-c", check], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(tmp_path / "data/mail.sqlite3") as database:
        database.execute("ALTER TABLE mailserver_account ADD COLUMN incompatible TEXT")
    result = subprocess.run([sys.executable, "-c", check], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and "No migration" in result.stderr


@pytest.mark.skipif(os.name != "posix", reason="Linux advisory lock")
def test_account_upgrade_operation_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_CONFIG", str(tmp_path / "config.json"))
    with cli.operation_lock():
        with pytest.raises(ValueError, match="Another"):
            with cli.operation_lock():
                pytest.fail("lock ignored")
    with cli.operation_lock():
        pass


def test_cli_help_does_not_load_configuration(tmp_path):
    for arguments in (["upgrade", "--help"], ["accounts", "--help"], ["accounts", "create", "--help"]):
        result = subprocess.run([sys.executable, "-m", "mailserver.cli", "--config", str(tmp_path / "absent"), *arguments],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr


def test_deployment_contract_is_shipped():
    root = Path(__file__).resolve().parents[1]
    assert json.loads((root / "deploy/upgrade.json").read_text()) == upgrade.CONTRACT
    assert 'cp "$SOURCE/deploy/upgrade.json" "$APP/deploy/"' in (root / "install.sh").read_text()
