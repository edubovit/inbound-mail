import argparse
import asyncio
import getpass
import os
import sys
from contextlib import nullcontext
from pathlib import Path


def require_root():
    if os.environ.get("MAIL_CONFIG") and (not hasattr(os, "geteuid") or os.geteuid() != 0):
        raise SystemExit("This operation requires root for a configured installation.")


def setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mailserver.settings")
    import django
    django.setup()


def initialize(username, password):
    from django.apps import apps
    from django.conf import settings
    from django.contrib.auth.password_validation import validate_password
    from django.db import connection

    from .models import Account

    database = Path(settings.DATABASES["default"]["NAME"])
    if database.exists():
        raise SystemExit("Database already exists. Upgrades and migrations are not supported.")
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
    reset = sub.add_parser("reset-admin", help="Root-only administrator recovery")
    reset.add_argument("username")
    export = sub.add_parser("export", help="Root-only all-mail tar export")
    export.add_argument("output", help="New output file, or - for stdout")
    sub.add_parser("smtp", help="Run the inbound SMTP listener")
    sub.add_parser("check", help="Validate application configuration and database")
    web = sub.add_parser("dev-web", help="Local-only development HTTP server")
    web.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.config:
        os.environ["MAIL_CONFIG"] = args.config
    if args.command in {"init", "reset-admin", "export"}:
        require_root()
        os.umask(0o077)
    setup()
    from django.core.exceptions import ValidationError
    try:
        if args.command in {"init", "reset-admin"}:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Repeat password: "):
                raise SystemExit("Passwords do not match.")
            if args.command == "init":
                initialize(args.username, password)
            else:
                from django.contrib.auth.password_validation import validate_password

                from .models import Account
                try:
                    user = Account.objects.get(username=args.username, role="ADMIN")
                except Account.DoesNotExist:
                    raise SystemExit("No administrator with that username exists.") from None
                validate_password(password, user)
                user.set_password(password)
                user.must_change_password = True
                user.save(update_fields=["password", "must_change_password"])
                print("Administrator password reset; existing sessions revoked.")
        elif args.command == "export":
            from .storage import export_mail
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


if __name__ == "__main__":
    main()
