# Configuration reference

[User guide](../README.md) · [Installation](installation.md) · [Operations](operations.md)

Production services load `/etc/inbound-mail/config.json` through `MAIL_CONFIG`.
The file is root-owned and readable by the `inbound-mail` group. The CLI wrapper
selects it automatically; direct CLI use accepts `--config PATH` before the command.

Edit valid JSON as root and preserve ownership/mode (`root:inbound-mail`, `0640`).
Settings load at process startup. Apply deliberate changes with:

```sh
sudo systemctl restart inbound-mail-web inbound-mail-smtp
sudo inbound-mail check
```

`check` validates the application and database connection, not public routing or
every possible configuration value. Keep positive integer values for limits.
Missing production `secret_key` or `data_dir` prevents startup.

## Mail limits

| JSON key | Default | Meaning |
| --- | --- | --- |
| `max_message_mib` | 25 | Entire SMTP message, including encoded attachments and headers |
| `mailbox_quota_mib` | 1024 | Default quota for newly created accounts |
| `disk_reserve_mib` | 1024 | Minimum free space, in addition to a write-safety allowance |
| `smtp_connections` | 16 | Concurrent SMTP connections across all senders |
| `smtp_messages_per_ip_hour` | 120 | MAIL attempts per source IP/hour |
| `smtp_messages_global_hour` | 1000 | MAIL attempts across senders/hour |
| `smtp_recipients` | 50 | Accepted recipients per SMTP transaction |

The installer accepts message limits from 1–100 MiB and quota/reserve values from
1–1,048,576 MiB. JSON editing is not subjected to those installer range checks;
large limits can exceed available memory or disk.

Existing mailbox quotas are edited in **Accounts**; changing the default does not
change them. Quotas count original bytes per recipient, not database overhead,
and do not reserve physical capacity. A lower quota can leave a mailbox over
limit; stored mail is retained and new deliveries are refused temporarily.

Disk checks allow for three times the incoming bytes across recipients, plus
1 MiB, above the configured reserve. Other host processes can still consume disk
space concurrently. Mail is not automatically expired or removed to make room.

Additional limits are implemented in code, not JSON settings: four connections
per IP, one active DATA transfer, up to 200 calls of each SMTP command per
connection, and a 120-second SMTP timeout. Competing DATA transfers get a temporary
rejection. SMTP rate counters
are in memory and reset when that service restarts.

## Identity, binding, and storage

| JSON key | Installed value or source | Meaning |
| --- | --- | --- |
| `domain` | Receiving-domain prompt | Domain accepted for local recipients |
| `smtp_hostname` | SMTP-hostname prompt (suggests `mail.<domain>`) | MX target and SMTP greeting/EHLO name; defaults to `domain` if omitted |
| `ui_url` | HTTPS URL prompt | Allowed web host, trusted CSRF origin |
| `secret_key` | Randomly generated | Django signing/session security secret; never publish |
| `data_dir` | `/var/lib/inbound-mail` | Directory containing `mail.sqlite3` |
| `smtp_host` | `0.0.0.0` | IPv4 SMTP bind address |
| `smtp_port` | 25 | SMTP listen port |

The receiving domain and SMTP hostname are independent: `example.com` can receive
mail through `mail.example.com` without an A record for `example.com`.
`smtp_host` is a bind address, not the DNS hostname.

Do not treat these as a domain-migration facility. Changing a domain, SMTP or UI hostname
also requires coordinated DNS, certificates, nginx, and sender configuration.
Changing `data_dir` does not move data or update systemd write permissions. Changing
`secret_key` invalidates existing authentication sessions.

The web listen port is in `inbound-mail-web.service`, not this JSON. The nginx
listen port, proxy target, and hostname are in its site file. Port changes require
coordinated service/proxy edits and external checks; JSON alone is insufficient.

## TLS paths

| JSON key | Purpose |
| --- | --- |
| `tls_cert` | Runtime full-chain PEM, installed at `/etc/inbound-mail/tls/fullchain.pem` |
| `tls_key` | Runtime private key, installed at `/etc/inbound-mail/tls/privkey.pem` |
| `certificate_source` | Full-chain source used by the refresh tool |
| `private_key_source` | Private-key source used by the refresh tool |

The certificate must cover `smtp_hostname` and the UI hostname, not the receiving
domain unless it is also used for one of those hostnames. The refresh tool uses
`domain` as the SMTP hostname when `smtp_hostname` is omitted.

Production SMTP requires a certificate/key pair to offer STARTTLS; sending servers
are not required to use TLS. Runtime copies are root-owned, group-readable, mode
`0640`. nginx references the installed runtime paths directly. Arbitrary path
changes need corresponding proxy and permission changes.

## Development versus production

Without `MAIL_CONFIG`, the application uses development settings: `mail.test`,
HTTP at `127.0.0.1:8000`, SMTP at `127.0.0.1:2525`, a fixed test secret, and no
secure-cookie/HTTPS enforcement. `MAIL_DEV_DATA` selects the local data directory;
otherwise it is `.local/data` in the checkout. Never expose this mode publicly.

`DEBUG` is false in both modes. Session age (12 hours), login throttles, the
10-second inbox refresh interval, and HTML preview limits are code settings, not
installer prompts. See [development](../CONTRIBUTING.md) before changing them.
