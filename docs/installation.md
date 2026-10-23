# Installation

[User guide](../README.md) · [Configuration](configuration.md) · [Operations](operations.md)

## Requirements

- Ubuntu 26.04 is the reference platform. Other Ubuntu/Debian installations are
  best-effort; Python 3.12+ and a running systemd are required.
- Root access, an interactive terminal (`/dev/tty`), and `ss` from `iproute2`.
- An available IPv4 TCP 25 listener, a free loopback application port, and an
  nginx HTTPS listener that can serve the UI hostname.
- A mail domain whose DNS you control. One receiving domain per installation.
- Internet access for OS packages, Python dependencies, and certificate issuance.

The installer installs Python venv support, nginx, Certbot, CA certificates, DNS
utilities, and curl. Download mode requires curl before installation begins.
Do not run the installer over an existing installation: it refuses owned paths
and an existing service account. Installation and uninstallation are the only
supported lifecycle actions.

## Run the installer

Run this from an interactive terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/edubovit/inbound-mail/master/install.sh | sudo bash
```

Already root? Use `bash` instead of `sudo bash`. No clone, archive URL, or checksum
entry is needed. The script resolves the repository's `master` branch through the
GitHub API, prints the commit ID, and downloads that exact source archive over
HTTPS. This installs the branch source, not a tagged release. GitHub API rate
limits or download failures stop installation before application-owned paths are
created. Extraction uses Python's data filter.

Piping into Bash grants the downloaded script root access. HTTPS and a pinned
archive revision are not an independent signature or publisher-trust check.
To review before execution:

```sh
curl -fsSL -o install.sh https://raw.githubusercontent.com/edubovit/inbound-mail/master/install.sh
# Inspect install.sh, then:
sudo bash install.sh
```

The complete script is parsed before installation starts. Prompts and child
processes read from `/dev/tty`, not the incoming script pipe; passwords are entered
without echo, not through arguments or environment variables.

Developers can still install a trusted checkout or extracted application archive:

```sh
sudo bash install.sh --source "$PWD"
```

The script asks for the receiving domain, public HTTPS UI URL, public IPv4,
loopback web port (default 20025), nginx TLS port, storage limits, DNS readiness,
certificate mode, and the first ADMIN username/password. A UI URL may include a
port but cannot contain a path. Confirmations precede installation changes.

## DNS and network

For mail to `username@inbox.example.com` and UI at `https://inbox.example.com`:

| Type | Name | Value |
| --- | --- | --- |
| A | `inbox.example.com` | Your public IPv4, e.g. documentation address `192.0.2.10` |
| MX | `inbox.example.com` | Priority **10**, target `inbox.example.com.` |

A different UI hostname needs its own A record. Use DNS-only records, not an
HTTP proxy. Leave unrelated mail-domain MX records unchanged. The installer binds
SMTP to IPv4; omit AAAA until IPv6 reception and HTTPS routing are explicitly
configured and tested. Standalone certificate mode rejects published AAAA records
and checks the supplied A and MX values before issuance.

Required inbound access:

| Port | Purpose |
| --- | --- |
| TCP 25 | Server-to-server SMTP reception |
| Public HTTPS port, normally TCP 443 | Browser UI |
| TCP 80 | Standalone ACME validation, including renewal |

The installer does not edit host/provider firewalls, NAT, Xray, or other upstream
routing. Keep the application port loopback-only. DNS resolution alone does not
prove delivery; some networks block outbound TCP 25 at the sender.

## Shared hosts

The installer validates existing nginx configuration and adds a dedicated site
at `/etc/nginx/sites-available/inbound-mail`, enabled by a symlink. An existing
nginx TLS port can host the new name after confirmation. A port owned by another
service cannot be taken over. Existing sites are not replaced.

The same hostname may be used on different nginx ports. For direct access at
`https://inbox.example.com:20002`, specify that full UI URL and nginx port `20002`.
Without an explicit port, HTTPS uses 443. When the public URL and nginx port differ,
the installer asks you to confirm that external routing is arranged.

nginx validates the generated site before reload. A duplicate name on the same
listener is rejected even when nginx reports it only as a warning. The new site's
enabled link is removed on rejection; the running configuration is not reloaded.
This validation occurs after app setup, so use the uninstaller to remove the
partial installation before retrying with a different hostname or port.

The installer does not merge paths into an existing server block. An existing
site that only serves `/monitoring/` still owns its hostname/listener. Adding mail
at `/` on that same listener requires deliberate manual integration, not a second
server block with the same name.

If another TLS router owns public 443, use its nginx backend port and arrange
routing for the UI hostname separately. The generated site listens on both nginx
address families. This does not enable IPv6 SMTP reception.

When nginx is newly installed, its package default site is disabled. No HTTP
redirect listener is added: use the HTTPS URL. A host already using TCP 80 must
use compatible operator-managed certificates rather than standalone ACME.

## Certificates

**Standalone:** the installer requests a certificate covering the receiving domain
and UI hostname. Certificate state is isolated under `/etc/inbound-mail/acme`;
the work directory is `/etc/inbound-mail/acme-work`. An optional external contact
email can be supplied. `inbound-mail-renew.timer` schedules checks twice daily
with a randomized delay. TCP 80 must be free and reachable for validation; the
installer does not stop other services to free it.

**Existing:** provide absolute paths to a PEM full chain and matching private key.
They must cover both hostnames and remain valid for at least another day. Copies
are placed in the application's private TLS directory. The operator owns renewal
and must run this after renewing the source files:

```sh
sudo python3 /opt/inbound-mail/deploy/refresh_tls.py
```

The refresh tool validates the files, replaces runtime copies, validates/reloads
nginx, and restarts only the SMTP application service. Existing-certificate mode
does not create the application's renewal timer. See [operations](operations.md)
for checking renewal failures.

## Verify installation

The installer checks application/database access, the local HTTPS health endpoint,
service state, and a local SMTP greeting. It cannot establish public reachability.

1. Open the public HTTPS URL without bypassing certificate validation.
2. Sign in, create a test account, and complete its required password change.
3. Send mail from an independent network and confirm it appears in that inbox.
4. Confirm unknown recipients and attempted external relaying are rejected.
5. Check available disk space and certificate renewal status.

Failures leave a partial installation for inspection; there is no automatic
rollback. Use the [uninstaller](operations.md#uninstall) to remove owned resources
before a fresh attempt. It does not remove installed shared OS packages.
