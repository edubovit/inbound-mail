# Account automation and credential archives

[User guide](../README.md) · [Operations](operations.md) · [Upgrade](upgrade.md)

These CLI commands are noninteractive. Production commands require root. Success
writes JSON to stdout and exits zero; any error exits nonzero. Passwords are never
accepted as command-line arguments, environment variables, or interactive input.
`reset-admin USER --password-file PATH` is the ADMIN-only recovery equivalent;
it also never prompts. Only fresh installation initialization prompts for a password.

## Create, inspect, change and delete

```sh
sudo inbound-mail accounts list
sudo inbound-mail accounts show alice
sudo inbound-mail accounts create alice --password-file /root/alice-password --role USER --quota-mib 1024
sudo inbound-mail accounts update alice --role ADMIN --quota-mib 2048
sudo inbound-mail accounts reset-password alice --password-file /root/alice-new-password
sudo inbound-mail accounts delete alice --confirm-delete
```

Password files must be regular UTF-8 files, owned by the command's effective user
(root under sudo), with no group/other permissions on Linux. Use mode 0600 or
0400. A single final LF or CRLF is removed; other spaces are preserved. Blank,
multiline, NUL-containing, and larger-than-4096-byte files are rejected. Symlinks
are rejected on Linux. Securely provision these files outside the repository;
never put real passwords in shell history or logs. Restrict their Windows ACLs
when testing locally; POSIX mode checks do not apply there.

Creation defaults to USER and the configured mailbox quota. Quotas must be
positive integer MiB values. Usernames use the same fixed-address rules as the UI;
there is no rename command. Invalid or duplicate accounts fail rather than update.
List/show output includes username, address, role, quota bytes and password-change
flag, **never password hashes**.

Create and reset default to requiring a password change at next login. Add
`--no-must-change-password` when provisioning a final password deliberately.
`accounts update` accepts either `--must-change-password` or
`--no-must-change-password`; omitted fields stay unchanged. Password resets revoke
existing sessions. Role/quota changes do not reset passwords. The final ADMIN
cannot be deleted or demoted.

Deletion requires `--confirm-delete`, never prompts, and permanently purges all
mail for that account. This is not an account-only delete. There is no undo.

## Export and import accounts only

```sh
sudo inbound-mail accounts export /root/accounts.json
sudo inbound-mail accounts import /root/accounts.json
```

The archive contains usernames, **password hashes**, USER/ADMIN roles, quota bytes,
and required-password-change flags. Imported users retain their passwords. It
does not contain plaintext passwords, mail, account IDs, sessions, login counters,
timestamps, or server configuration. This is separate from the all-mail tar export.

Exports create a new mode-0600 JSON file and refuse overwriting. The file is not
encrypted: treat it as credential material and protect any transferred copies.
Imports apply the same private-file ownership/mode checks as password files and
limit input to 16 MiB. Use only trusted archives; an archive can create ADMINs.

Import accepts only the current `inbound-mail-accounts-1` format, the same receiving
domain, valid current account fields, and PBKDF2-SHA256 password hashes. There are
no format conversions, legacy hash adapters, merge, overwrite, or skip options.
Unsupported credentials also cause export to fail rather than omit accounts.

All accounts are validated before writing. Duplicate usernames within the archive
or collisions with existing accounts reject the **entire import**. Creation is
one database transaction; a failure rolls it back. Existing accounts and mail are
left alone. Imported accounts have empty mailboxes. The resulting installation
must have at least one ADMIN.

For a fresh installation, choose a temporary first-admin username **not present
in the archive**. Import, verify an imported ADMIN can sign in, then delete the
temporary admin with `--confirm-delete`. Do not delete the final administrator to
try to clear a collision. This does not restore exported mail.

Account commands and upgrades share a nonblocking local operation lock. A busy
lock fails immediately; scripts decide whether and when to retry. Do not run other
maintenance tools concurrently.
