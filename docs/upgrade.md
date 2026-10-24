# Best-effort upgrades

[User guide](../README.md) · [Operations](operations.md) · [Account archives](accounts-cli.md)

```sh
sudo inbound-mail upgrade --check
sudo inbound-mail upgrade
```

`--check` downloads/builds and validates a candidate without stopping services or
replacing installed files. It creates temporary staging files and the private
backup parent directory if needed. A later upgrade repeats all checks; it does
not reuse the candidate. Both commands are noninteractive and root-only.

The default target is the GitHub `master` commit resolved at command start. Use
`--revision FULL_40_CHARACTER_COMMIT_ID` for a fixed target, or
`--source /absolute/path/to/trusted-source` for a checkout/extracted release. Only
one may be supplied. Source and build dependencies execute as root: HTTPS and
revision pinning are not independent publisher authentication. Review the source
and trust the dependency sources before running.

## Preconditions and scope

Upgrades support the installer's standard native Linux layout: `/opt/inbound-mail`,
`/etc/inbound-mail/config.json`, `/var/lib/inbound-mail`, and both owned systemd
services. Run with the installed virtual-environment Python (the installed CLI
wrapper already does). Both services must be active; systemd drop-ins, custom
working directories/users/data paths, failed nginx validation, broken HTTPS/SMTP
TLS health, incompatible deployment contract or database schema, unavailable
dependencies, and insufficient disk space cause failure, not attempted repair.

There is **no backward-compatibility promise and no schema/configuration migration**.
The candidate must work with the current configuration and its freshly generated
SQLite schema must exactly match the existing schema. The command never calls the
installer, requests certificates, changes DNS/firewalls/proxy routes, or updates OS
packages/systemd unit files. A change requiring those actions needs separate
operator work, not more upgrade flags.

Do not overlap upgrades with certificate renewal, uninstall, manual database work,
or other maintenance. Account CLI operations and upgrades use a nonblocking lock;
this is not a global lock for external tools. Ensure there is room for application,
configuration and database backups in addition to staging and the disk reserve.

## Execution and failure handling

1. Check the installation and existing HTTPS/SMTP health.
2. Build a wheelhouse and isolated candidate environment. Verify dependency
   consistency, configuration checks, matching database schema/integrity, and
   certificate/key loading before downtime.
3. Stop only the two mail services. Save a private backup of application/venv,
   configuration, SQLite and owned service units under
   `/var/backups/inbound-mail/upgrade-…`. The printed path identifies this backup.
4. Replace application/deployment-tool files and reinstall the prepared wheels
   offline. Check dependencies and service-user application access. Start both
   mail services, then check HTTPS `/health/` and local SMTP STARTTLS.

Mail reception and the UI are unavailable during steps 3–4. Sending servers
normally retry connection failures, but retry duration is outside this app's
control. After completion, verify login and a real external delivery yourself.
The built-in probes do not prove Internet reachability.

Any failed step aborts. If activation fails after stopping services, the command
attempts to restore the previous application/venv and restart the mail services.
It **does not restore the database or configuration automatically**: newly accepted
mail must not be discarded by a rollback. No migration was performed. If rollback
itself fails, inspect the error and service state and recover manually from the
printed backup; do not rerun installation or purge data as a repair attempt.

Backups include password hashes, configuration secrets, TLS private keys and mail.
They remain root-private, are not automatically pruned, and are not removed by
uninstall. Protect them and remove unneeded snapshots deliberately. These local
rollback files are not an off-server backup strategy.

## Bootstrapping an installation without the command

Do not run the installer over existing data. From an inspected, trusted source
directory containing this CLI, run with the installation's interpreter:

```sh
cd /root/inbound-mail-source
sudo /opt/inbound-mail/venv/bin/python -m mailserver.cli \
  --config /etc/inbound-mail/config.json upgrade --source "$PWD" --check
sudo /opt/inbound-mail/venv/bin/python -m mailserver.cli \
  --config /etc/inbound-mail/config.json upgrade --source "$PWD"
```

The source directory name is an example, not an automatic download location. This
uses the current command without first overwriting installed code. All normal
checks still apply; it is not a legacy migration path. If the installed Python or
dependencies cannot run this command, stop and perform reviewed manual maintenance.
