import base64
import json
import os
import re
import stat

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Account

FORMAT = "inbound-mail-accounts-1"
FIELDS = {"username", "password", "role", "quota_bytes", "must_change_password"}


def read_private_file(path, limit):
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    with open(os.open(path, flags), "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Input must be a regular file.")
        if os.name == "posix" and (info.st_mode & 0o077 or info.st_uid != os.geteuid()):
            raise ValueError("Secret input files must be owned by the caller and have mode 0600 or 0400.")
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Input file exceeds the size limit.")
    return data.decode("utf-8")


def read_password(path):
    value = read_private_file(path, 4096)
    value = value.removesuffix("\n").removesuffix("\r")
    if not value or any(char in value for char in "\r\n\x00"):
        raise ValueError("Password file must contain one nonempty UTF-8 line.")
    return value


def public_account(account):
    return {"username": account.username, "address": account.address, "role": account.role,
            "quota_bytes": account.quota_bytes, "must_change_password": account.must_change_password}


def find_account(username):
    try:
        return Account.objects.get(username=username)
    except Account.DoesNotExist:
        raise ValueError("Account does not exist.") from None


def protect_admin(account, role=None, deleting=False):
    if account.role == "ADMIN" and (deleting or role == "USER") and Account.objects.filter(role="ADMIN").count() == 1:
        raise ValueError("Cannot delete or demote the final administrator.")


def validate_record(record):
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ValueError("Invalid account record fields.")
    if (not all(type(record[key]) is str for key in ("username", "password", "role"))
            or type(record["quota_bytes"]) is not int or not 0 < record["quota_bytes"] <= 2**63 - 1
            or type(record["must_change_password"]) is not bool):
        raise ValueError("Invalid account record types or quota.")
    password = record["password"]
    if not re.fullmatch(r"pbkdf2_sha256\$[1-9][0-9]{0,7}\$[A-Za-z0-9]+\$[A-Za-z0-9+/]{43}=", password):
        raise ValueError("Unsupported or malformed password hash; only PBKDF2-SHA256 is accepted.")
    if len(base64.b64decode(password.rsplit("$", 1)[1], validate=True)) != 32:
        raise ValueError("Malformed password hash.")
    account = Account(**record)
    try:
        account.full_clean(validate_unique=False)
    except ValidationError:
        raise ValueError("Invalid account record values.") from None
    return account


def export_accounts(output):
    with transaction.atomic():
        rows = list(Account.objects.order_by("username").values(*sorted(FIELDS)))
    for row in rows:
        validate_record(row)
    document = {"format": FORMAT, "domain": settings.MAIL_DOMAIN, "accounts": rows}
    with open(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as target:
        json.dump(document, target, indent=2)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    return {"exported": len(rows)}


def import_accounts(source):
    try:
        document = json.loads(read_private_file(source, 16 * 1024**2))
    except json.JSONDecodeError:
        raise ValueError("Invalid account archive JSON.") from None
    if (not isinstance(document, dict) or set(document) != {"format", "domain", "accounts"}
            or document["format"] != FORMAT or document["domain"] != settings.MAIL_DOMAIN
            or not isinstance(document["accounts"], list)):
        raise ValueError("Unsupported account archive format or receiving domain.")
    accounts = [validate_record(row) for row in document["accounts"]]
    names = [account.username for account in accounts]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate usernames in account archive.")
    with transaction.atomic():
        if Account.objects.filter(username__in=names).exists():
            raise ValueError("An imported username already exists; nothing was imported.")
        if not Account.objects.filter(role="ADMIN").exists() and not any(a.role == "ADMIN" for a in accounts):
            raise ValueError("Import would leave no administrator.")
        for account in accounts:
            account.save(force_insert=True)
    return {"imported": len(accounts)}


def run(args):
    action = args.account_command
    if action == "export":
        return export_accounts(args.output)
    if action == "import":
        return import_accounts(args.input)
    if action == "list":
        return [public_account(account) for account in Account.objects.order_by("username")]
    if action == "show":
        return public_account(find_account(args.username))
    password = read_password(args.password_file) if action in {"create", "reset-password"} else None
    with transaction.atomic():
        account = Account(username=args.username) if action == "create" else find_account(args.username)
        if action == "delete":
            protect_admin(account, deleting=True)
            account.delete()
            return {"deleted": args.username}
        if action in {"create", "update"}:
            protect_admin(account, role=args.role)
            if args.role is not None:
                account.role = args.role
            if args.quota_mib is not None:
                if not 0 < args.quota_mib <= (2**63 - 1) // 1024**2:
                    raise ValueError("Quota must be a positive MiB value within SQLite's integer range.")
                account.quota_bytes = args.quota_mib * 1024**2
        if args.must_change_password is not None:
            account.must_change_password = args.must_change_password
        if password is not None:
            validate_password(password, account)
            account.set_password(password)
        account.full_clean()
        account.save()
        return public_account(account)
