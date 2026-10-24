import argparse
import asyncio
import getpass
import json
import os
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path


def require_root():
    if os.environ.get("MAIL_CONFIG") and (not hasattr(os, "geteuid") or os.geteuid() != 0):
        raise SystemExit("This operation requires root for a configured installation.")


def setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mailserver.settings")
    import django
    django.setup()


@contextmanager
def operation_lock():
    if not os.environ.get("MAIL_CONFIG"):
        yield
        return
    import fcntl
    path = Path(os.environ["MAIL_CONFIG"]).parent / "operation.lock"
    with open(path, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another account/upgrade operation is running.") from None
        yield


def account_parser(sub):
    accounts = sub.add_parser("accounts", help="Noninteractive account management and credential export/import")
    actions = accounts.add_subparsers(dest="account_command", required=True)
    actions.add_parser("list", help="List accounts as JSON, without password hashes")
    actions.add_parser("show").add_argument("username")
    for action in ("create", "update", "reset-password", "delete"):
        command = actions.add_parser(action)
        command.add_argument("username")
        if action in {"create", "reset-password"}:
            command.add_argument("--password-file", type=Path, required=True)
        if action in {"create", "update"}:
            command.add_argument("--role", choices=["USER", "ADMIN"], default="USER" if action == "create" else None)
            command.add_argument("--quota-mib", type=int)
        if action == "delete":
            command.add_argument("--confirm-delete", action="store_true", required=True,
                                 help="Permanently delete this account and all its mail")
        else:
            command.add_argument("--must-change-password", action=argparse.BooleanOptionalAction,
                                 default=None if action == "update" else True)
    actions.add_parser("export", help="Write credentials to a new private JSON file; no mail").add_argument("output", type=Path)
    actions.add_parser("import", help="Atomically create accounts; refuse collisions and incompatible archives").add_argument("input", type=Path)


def initialize(username, password):
    from django.apps import apps
    from django.conf import settings
    from django.contrib.auth.password_validation import validate_password
    from django.db import connection

    from .models import Account

    database = Path(settings.DATABASES["default"]["NAME"])
    if database.exists():
        raise SystemExit("Database already exists. Initialization never upgrades or migrates it.")
    user = Account(username=username, role="ADMIN")
    user.set_password(password)
    user.full_clean(exclude=["id"], validate_unique=False)
    validate_password(password, user)
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA auto_vacuum=FULL")
    with connection.schema_editor() as editor:
        for model in apps.get_models():
            editor.create_model(model)
    Account.objects.create_user(username, password, role="ADMIN")
    print("Initialized a fresh database and first administrator.")


def main():
    parser = argparse.ArgumentParser(prog="inbound-mail")
    parser.add_argument("--config", help="Path to production JSON configuration")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Initialize a fresh installation; never upgrades")
    init.add_argument("username")
    reset = sub.add_parser("reset-admin", help="Noninteractive root-only administrator recovery")
    reset.add_argument("username")
    reset.add_argument("--password-file", type=Path, required=True)
    reset.set_defaults(account_command="reset-password", must_change_password=True)
    account_parser(sub)
    upgrade = sub.add_parser("upgrade", help="Best-effort native upgrade; no schema/configuration migrations")
    target = upgrade.add_mutually_exclusive_group()
    target.add_argument("--source", type=Path, help="Trusted local source directory instead of GitHub")
    target.add_argument("--revision", help="Full Git commit ID instead of current master")
    upgrade.add_argument("--check", action="store_true", help="Prepare/check candidate without installing or stopping services")
    export = sub.add_parser("export", help="Root-only all-mail tar export")
    export.add_argument("output", help="New output file, or - for stdout")
    sub.add_parser("smtp", help="Run the inbound SMTP listener")
    sub.add_parser("check", help="Validate application configuration and database")
    web = sub.add_parser("dev-web", help="Local-only development HTTP server")
    web.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.config:
        os.environ["MAIL_CONFIG"] = args.config
    if args.command in {"init", "reset-admin", "export", "accounts", "upgrade"}:
        require_root()
        os.umask(0o077)
    if args.command == "upgrade":
        from .upgrade import run
        try:
            with operation_lock():
                run(args)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise SystemExit(f"Upgrade failed: {error}") from None
        return
    setup()
    from django.core.exceptions import ValidationError
    try:
        if args.command == "accounts":
            from .accounts import run
            with operation_lock():
                print(json.dumps(run(args)))
        elif args.command == "init":
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Repeat password: "):
                raise SystemExit("Passwords do not match.")
            with operation_lock():
                initialize(args.username, password)
        elif args.command == "reset-admin":
            from django.db import transaction

            from .accounts import find_account, run
            with operation_lock(), transaction.atomic():
                if find_account(args.username).role != "ADMIN":
                    raise ValueError("No administrator with that username exists.")
                print(json.dumps(run(args)))
        elif args.command == "export":
            from .storage import export_mail
            with operation_lock():
                with nullcontext(sys.stdout.buffer) if args.output == "-" else open(args.output, "xb") as target:
                    for chunk in export_mail():
                        target.write(chunk)
        elif args.command == "smtp":
            from .smtp import serve
            asyncio.run(serve())
        elif args.command == "check":
            from django.core.management import call_command

            from .models import Account
            call_command("check")
            print(f"Database accessible; {Account.objects.count()} accounts.")
        elif args.command == "dev-web":
            from django.conf import settings
            from django.core.management import call_command
            if not settings.DEVELOPMENT:
                raise SystemExit("Use the production WSGI service with a configured installation.")
            call_command("runserver", f"127.0.0.1:{args.port}", use_reloader=False)
    except ValidationError as error:
        raise SystemExit("; ".join(error.messages)) from error
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
