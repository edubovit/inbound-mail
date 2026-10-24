import json
import os
import re
import shlex
import shutil
import smtplib
import sqlite3
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

APP = Path("/opt/inbound-mail")
CONFIG = Path("/etc/inbound-mail/config.json")
BACKUPS = Path("/var/backups/inbound-mail")
UNITS = Path("/etc/systemd/system")
SERVICES = ("inbound-mail-web", "inbound-mail-smtp")
CONTRACT = {"layout": 1, "configuration": 1, "upgrade": 1}
SOURCE_FILES = ("mailserver", "deploy", "install.sh", "requirements.txt", "pyproject.toml")


def command(*args, cwd=None, capture=False):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PIP_NO_INPUT": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    env.pop("PYTHONPATH", None)
    return subprocess.run([str(arg) for arg in args], cwd=cwd or APP.parent, env=env, check=True,
                          text=True, stdout=subprocess.PIPE if capture else sys.stderr,
                          stderr=sys.stderr, stdin=subprocess.DEVNULL, timeout=600).stdout


def schema(database):
    return database.execute("SELECT type, name, tbl_name, sql FROM sqlite_master "
                            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()


def expected_schema():
    from django.apps import apps
    from django.conf import settings
    from django.db import connection

    settings.DATABASES["default"]["NAME"] = ":memory:"
    with connection.schema_editor() as editor:
        for model in apps.get_models():
            editor.create_model(model)
    return schema(connection.connection)


def check_candidate():
    from django.conf import settings
    from django.core.management import call_command

    call_command("check", stdout=sys.stderr)
    expected = expected_schema()
    path = settings.DATA_DIR / "mail.sqlite3"
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as database:
        if schema(database) != expected:
            raise ValueError("Database schema differs from the candidate. No migration is supported.")
        if database.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("Database integrity check failed.")
        if database.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Database foreign-key check failed.")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(settings.TLS_CERT, settings.TLS_KEY)


def download(url, output):
    command("curl", "--fail", "--silent", "--show-error", "--location", "--proto", "=https",
            "--proto-redir", "=https", "--tlsv1.2", "--connect-timeout", "15", "--max-time", "300",
            "--output", output, url)


def get_source(work, source, revision):
    if source:
        return Path(source).resolve()
    if revision is None:
        download("https://api.github.com/repos/edubovit/inbound-mail/commits/master", work / "commit.json")
        revision = json.loads((work / "commit.json").read_text())["sha"]
    if not re.fullmatch("[a-f0-9]{40}", revision):
        raise ValueError("Revision must be a full lowercase Git commit ID.")
    print(f"Preparing revision {revision}", file=sys.stderr)
    download(f"https://codeload.github.com/edubovit/inbound-mail/tar.gz/{revision}", work / "source.tar.gz")
    with tarfile.open(work / "source.tar.gz") as archive:
        if any(not (item.isfile() or item.isdir()) for item in archive.getmembers()):
            raise ValueError("Source archive contains links or special files.")
        archive.extractall(work / "source", filter="data")
    return work / "source" / f"inbound-mail-{revision}"


def prepare(work, source):
    if json.loads((source / "deploy" / "upgrade.json").read_text()) != CONTRACT:
        raise ValueError("Unsupported deployment contract. No configuration/layout migration is supported.")
    staged = work / "candidate"
    staged.mkdir()
    for name in SOURCE_FILES:
        src = source / name
        if src.is_dir():
            shutil.copytree(src, staged / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, staged / name)
    wheels = work / "wheels"
    command(sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check", "--wheel-dir", wheels, staged, cwd=work)
    wheel, = wheels.glob("inbound_mail-*.whl")
    command(sys.executable, "-m", "venv", work / "venv", cwd=work)
    python = work / "venv/bin/python"
    command(python, "-m", "pip", "install", "--no-index", "--find-links", wheels, wheel, cwd=work)
    command(python, "-m", "pip", "check", cwd=work)
    command(python, "-m", "mailserver.upgrade", cwd=work)
    return staged, wheels, wheel


def directory_size(path):
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def preflight():
    if sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError("Upgrade requires root on a native Linux installation.")
    if Path(os.environ.get("MAIL_CONFIG", "")) != CONFIG:
        raise ValueError("Upgrade supports only the standard /etc/inbound-mail/config.json installation.")
    for path in (APP, CONFIG.parent, BACKUPS):
        if path.is_symlink() or (path.exists() and (path.stat().st_uid != 0 or path.stat().st_mode & 0o022)):
            raise ValueError("Application, configuration and backup paths must be root-owned and not writable by others or symlinked.")
    if not (CONFIG.parent / "owned").is_file() or not (APP / "venv/bin/python").is_file():
        raise ValueError("No complete owned installation found.")
    if Path(sys.prefix) != APP / "venv":
        raise ValueError("Run upgrade with the installation's virtual-environment Python.")
    config = json.loads(CONFIG.read_text())
    if config["data_dir"] != "/var/lib/inbound-mail":
        raise ValueError("Nonstandard data directories require manual maintenance.")
    for service in SERVICES:
        command("systemctl", "is-active", "--quiet", service)
        properties = command("systemctl", "show", service,
                             "--property=WorkingDirectory,User,Group,Environment,FragmentPath,DropInPaths", capture=True)
        values = dict(line.split("=", 1) for line in properties.splitlines())
        if (values.get("WorkingDirectory") != str(APP) or values.get("User") != "inbound-mail"
                or values.get("Group") != "inbound-mail"
                or set(shlex.split(values.get("Environment", ""))) != {f"MAIL_CONFIG={CONFIG}", "PYTHONDONTWRITEBYTECODE=1"}
                or values.get("FragmentPath") != str(UNITS / f"{service}.service") or values.get("DropInPaths")):
            raise ValueError("Unsupported service layout or systemd overrides; use manual maintenance.")
    command("nginx", "-t")
    verify(config)
    return config


def snapshot(backup, config):
    shutil.copytree(APP, backup / "app", symlinks=True)
    shutil.copytree(CONFIG.parent, backup / "config", symlinks=True)
    database = Path(config["data_dir"]) / "mail.sqlite3"
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as source:
        with sqlite3.connect(backup / "mail.sqlite3") as target:
            source.backup(target)
    for service in SERVICES:
        shutil.copy2(UNITS / f"{service}.service", backup)


def activate(staged, wheels, wheel):
    for name in SOURCE_FILES:
        target = APP / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if (staged / name).is_dir():
            shutil.copytree(staged / name, target)
        else:
            shutil.copy2(staged / name, target)
    command(APP / "venv/bin/python", "-m", "pip", "install", "--no-index", "--find-links", wheels,
            "--force-reinstall", wheel, cwd=APP)
    command("chmod", "-R", "a+rX", APP)
    command(APP / "venv/bin/python", "-m", "pip", "check", cwd=APP)
    command("runuser", "-u", "inbound-mail", "--", APP / "venv/bin/python", "-m", "mailserver.cli",
            "--config", CONFIG, "check", cwd=APP)


def verify(config):
    command("systemctl", "is-active", "--quiet", *SERVICES)
    request = Request(config["ui_url"].rstrip("/") + "/health/")
    with urlopen(request, timeout=10) as response:
        if response.url != request.full_url or response.read(32) != b"ok\n":
            raise ValueError("Unexpected HTTPS health response.")
    with smtplib.SMTP("127.0.0.1", int(config["smtp_port"]), timeout=10) as client:
        client._host = config.get("smtp_hostname", config["domain"])
        client.ehlo()
        client.starttls(context=ssl.create_default_context())
        if client.ehlo()[0] != 250 or client.has_extn("auth"):
            raise ValueError("SMTP verification failed.")


def apply(staged, wheels, wheel, backup, config):
    stopped = False
    changed = False
    try:
        stopped = True
        command("systemctl", "stop", *SERVICES)
        for service in SERVICES:
            if command("systemctl", "show", service, "--property=ActiveState", "--value", capture=True).strip() != "inactive":
                raise ValueError("A mail service did not stop; application was not replaced.")
        snapshot(backup, config)
        changed = True
        activate(staged, wheels, wheel)
        command("systemctl", "start", *SERVICES)
        time.sleep(2)
        verify(config)
    except BaseException:
        if stopped:
            command("systemctl", "stop", *SERVICES)
            if changed:
                shutil.rmtree(APP)
                shutil.copytree(backup / "app", APP, symlinks=True)
            command("systemctl", "start", *SERVICES)
            print("Previous application restarted. Database/configuration were not rolled back.", file=sys.stderr)
        raise


def run(args):
    config = preflight()
    check_space(config)
    with tempfile.TemporaryDirectory(prefix="inbound-mail-upgrade-", dir=APP.parent) as directory:
        work = Path(directory)
        source = get_source(work, args.source, args.revision)
        staged, wheels, wheel = prepare(work, source)
        check_space(config)
        if args.check:
            print("Candidate checks passed; no services stopped or installed files changed.")
            return
        backup = BACKUPS / datetime.now(timezone.utc).strftime("upgrade-%Y%m%dT%H%M%S%fZ")
        backup.mkdir(mode=0o700)
        print(f"Private rollback backup: {backup}", flush=True)
        apply(staged, wheels, wheel, backup, config)
        print("Upgrade complete. Accounts, mail, configuration and proxy routing retained.")


def check_space(config):
    reserve = int(config.get("disk_reserve_mib", 1024)) * 1024**2
    required = directory_size(APP) + directory_size(CONFIG.parent) + (Path(config["data_dir"]) / "mail.sqlite3").stat().st_size
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    if min(shutil.disk_usage(BACKUPS).free, shutil.disk_usage(APP).free) < required * 2 + reserve:
        raise ValueError("Insufficient free disk for upgrade backup and reserve.")


if __name__ == "__main__":
    from .cli import setup
    setup()
    check_candidate()
