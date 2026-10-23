# Development guide

Inbound is a small Python application with server-rendered pages, native services,
and no frontend build system. Keep changes readable, narrowly scoped, and tested.
The [user guide](README.md) and [operator documentation](docs/installation.md)
describe the supported product, not a roadmap.

## Documentation is part of every change

- Document only implemented, supported behavior. Verify claims against source,
  configuration, and tests; do not infer them from an intended design.
- Update affected documentation in the same change as code. Remove stale text and
  screenshots rather than appending corrections, dated notes, or change histories.
- Keep README short: purpose, features, installation, configuration, and links.
  Put operator detail in `docs/` and development instructions here.
- Do not maintain changelogs, past-version comparisons, incident narratives, or
  saved test-run counts in these guides. Use review/CI output for execution results.
- Use example domains, documentation IPs, relative workspace paths, and synthetic
  data. Never copy private deployment notes or credentials into public documents.
- Refresh screenshots when the visible UI changes. Run the documentation/link
  checks before submitting changes.

## Local setup

Use Python 3.12+ and Git. Linux is required for native installer/systemd testing;
the application and pytest suite can also run on Windows. Node.js is optional for
JavaScript syntax checks. Browser checks require a Playwright MCP environment.

From the repository root on Linux/macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m mailserver.cli init admin
python -m mailserver.cli dev-web
```

In another terminal, activate the same environment and run:

```sh
python -m mailserver.cli smtp
```

Windows PowerShell, without changing script execution policy:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m mailserver.cli init admin
.\.venv\Scripts\python.exe -m mailserver.cli dev-web
```

Use that interpreter in a second terminal for `-m mailserver.cli smtp`. Run commands
from the checkout root; there is no `manage.py`. Initialization prompts for the
first admin password and refuses an existing database.

Development serves HTTP on `127.0.0.1:8000`, SMTP on `127.0.0.1:2525`, and accepts
addresses at `mail.test`. It has a fixed test secret and no public TLS setup.
Never expose it to untrusted networks. `DEBUG` remains false. The web command uses
no autoreloader: restart it after Python changes.

Without `MAIL_CONFIG`, data lives in `.local/data`. For another disposable database,
set `MAIL_DEV_DATA` consistently in every app process:

```sh
export MAIL_DEV_DATA="$PWD/.local/sandbox"
```

```powershell
$env:MAIL_DEV_DATA = Join-Path $PWD '.local/sandbox'
```

Unset `MAIL_CONFIG` when using development mode. Production behavior is selected
by that variable or CLI `--config PATH`, not by `DEBUG`. Never run tests against
a production data directory. See [configuration](docs/configuration.md).

## Code map and architecture

| Location | Responsibility |
| --- | --- |
| `mailserver/settings.py` | Development/production settings and configuration defaults |
| `mailserver/models.py` | Accounts, messages, and login-attempt counters |
| `mailserver/storage.py` | Atomic delivery, quota accounting, streaming export |
| `mailserver/smtp.py` | aiosmtpd protocol hooks, rate/concurrency limits, STARTTLS |
| `mailserver/views.py`, `forms.py`, `urls.py` | Web behavior, validation, authorization, routes |
| `mailserver/middleware.py` | Forced-password-change gate and response security headers |
| `mailserver/mime.py` | MIME parsing, bounded previews, HTML sanitization, attachment names |
| `mailserver/templates/`, `static/` | Django templates, CSS, and inbox polling JavaScript |
| `mailserver/cli.py` | Fresh schema initialization, recovery, export, dev/service entry points |
| `mailserver/wsgi.py` | Production WSGI application |
| `install.sh`, `deploy/` | Native installation/removal, certificate refresh, and shared nginx integration |
| `tests/` | pytest suites and Playwright MCP snippets |
| `tools/` | Preview fixtures, browser rendering, SMTP checks, release and docs tools |

### Storage and delivery

SQLite is shared by the web and SMTP processes. `Account` extends Django's
`AbstractBaseUser`; its role is USER or ADMIN, and it has a fixed username, quota,
and required-password-change flag. `Message` stores the original bytes as a BLOB
plus owner, size, sender/subject metadata, received time and read state. Deleting
an account cascades to its messages. Django sessions and content types also have
tables. `LoginAttempt` stores keyed counters, not plaintext login identifiers.

Schema initialization uses Django's schema editor to create a fresh database;
there are no migration files or migration/upgrade commands. It enables full
auto-vacuum; connections use synchronous EXTRA, secure-delete, a 15-second lock
timeout, and IMMEDIATE transactions. Use a new disposable database after changing
models. Do not silently add schema changes to an installation path that rejects
existing data.

SMTP validates recipients at RCPT and revalidates them at DATA. A DATA handler
passes synchronous storage work through `sync_to_async`. Delivery deduplicates
recipients, checks message size, disk reserve and every recipient's quota, and
stores all recipients atomically. A success reply follows commit. Keep the
all-or-nothing and durable-before-acceptance properties intact. A failed commit
must produce a retryable SMTP response, not silent loss or an outbound bounce.

Sender/subject list metadata is parsed from at most the first 64 KiB of the
message. Original bytes are preserved. Inbox queries defer the BLOB field; do not
load bodies while polling or listing messages. Export streams one message at a
time with an initial message-ID cutoff, not a point-in-time database snapshot.

### Web and security boundaries

Every mailbox, body, attachment, and mutation lookup must be scoped to the logged-in
account. ADMIN privileges allow account management and all-mail export, not direct
cross-mailbox browsing. Enforce permissions server-side even when controls are hidden.

Keep CSRF on all mutations and use POST plus confirmation for destructive actions.
Preserve final-admin checks, password-reset session invalidation, and required
password changes. Save only intended model fields to avoid overwriting concurrent
role/quota changes. The application does not use Django's stock admin site.

HTML email gets nh3 sanitization, an isolated sandboxed iframe, and a stricter CSP
than the application UI. Never weaken that policy to fix UI scripting. The iframe
can load the application's stylesheet but not email-provided active content.
Attachment downloads are not malware scanning. The [security guide](docs/security.md)
defines the user-visible guarantees and limitations.

### UI and refresh

Templates are rendered on the server; there is no npm build or component framework.
Static assets are served through explicit views. Package-data patterns in
`pyproject.toml` must include new assets/templates.

The UI follows Swiss After Dark's Grid Rail design: charcoal and bone surfaces,
a scarlet-edged index rail, one-email-per-row inbox, two-column account tiles, and square
bone primary actions. Tokens live in `static/style.css`; the sandboxed message
stylesheet uses the same palette without permitting email-provided styles. Login
uses Arial/Helvetica. Keep the mobile rail, tile-wide links, focus outlines, and
below-collection Create action consistent. There are no monitoring timelines or
synthetic status measurements in this mail UI. See the [design contract](docs/design.md).

`static/select.js` progressively enhances single-select fields with a styled
combobox/listbox. The underlying select still submits the form; without JavaScript
it remains native. Test opening, selection, arrow/Home/End keys, Enter/Space,
Escape, Tab, type-ahead, outside clicks, reset/change events, dynamic fields, and
viewport-edge placement. Do not add an unstyled option menu or change authentication
and CSRF behavior to accommodate controls.

`static/inbox.js` fetches `/inbox/updates/` every 10 seconds without a page reload.
It preserves the page query, skips unchanged markup, restores focused links,
pauses while hidden/offline, resumes on return, and retains the inbox on errors.
Requests have an 8-second abort timeout and are serialized. Auth redirects navigate
away; account/role changes trigger a reload. Manual refresh and server-rendered
content must keep working with JavaScript disabled.

## Automated checks

```sh
python -m pytest -q
python -m pip install ruff
python -m ruff check mailserver tests tools deploy
python tools/check_docs.py
node --check mailserver/static/inbox.js
node --check mailserver/static/select.js
git diff --check
```

Ruff is an optional developer tool, not in `requirements-dev.txt`. Node is needed
only for the shown syntax check or your browser tooling. pytest configuration is
in `pyproject.toml`; `--nomigrations` matches fresh-schema creation. Test fixtures
use temporary storage and fast test-only password hashing; production hashing
must not be weakened to speed tests.

Coverage areas include authentication, CSRF, role isolation, password lifecycle,
HTML/MIME handling, real SMTP sockets, size/rate/connection limits, atomic quota
checks, storage failures, export contents, persistence/concurrency, polling metadata,
packaging, documentation links, and publication tooling. Run the relevant focused
suite while editing, then the full suite. Do not substitute a stored test count
or a successful health check for an executed test run.

## Browser checks and screenshots

### Isolated local preview

```sh
python -m tools.seed_preview
MAIL_DEV_DATA="$PWD/.local/ui-preview" python -m mailserver.cli dev-web
```

In a second terminal:

```sh
MAIL_DEV_DATA="$PWD/.local/ui-preview" python -m mailserver.cli smtp
```

On PowerShell, set `$env:MAIL_DEV_DATA = Join-Path $PWD '.local/ui-preview'` before
starting each service with the venv interpreter. The seed tool creates synthetic
mail and disposable fixed credentials. It refuses to overwrite a database. Start
from a fresh preview fixture when rerunning stateful browser scenarios; do not
delete a data directory unless you have confirmed it contains only disposable data.

Run `tests/browser-dark-ui.js` using Playwright MCP's code-file tool. Leave its
inbox open, run `python -m tools.seed_preview --deliver`, then execute
`tests/browser-inbox-refresh.js`. These check styling, safe HTML, mobile layout,
real SMTP arrival without reloading, HTTP-error retry, visibility/offline behavior,
and session expiry. They are MCP snippets, not a standalone npm test suite.

For the cross-browser UI suite, keep the isolated preview running and install the
optional browser tooling (not runtime dependencies):

```sh
python -m pip install playwright==1.63.0
python -m playwright install chromium firefox webkit
python tools/check_ui.py
```

The runner uses only `http://127.0.0.1:8000` and the fixed synthetic preview accounts.
It creates and deletes test accounts. It checks 1440, 768, 390 and 320 px layouts,
tile navigation and stable geometry, dropdown keyboard/touch behavior, account
actions, mail attachments, validation, empty states, and reduced-motion/high-contrast
behavior. Results/screenshots go to `.local/ui-checks`. Use `--engines chromium`
for a focused run. All engines must be installed to claim full browser coverage;
WebKit automation is not a native Safari or physical-device audit.
Login throttles still apply in the preview. Repeated runs can reach the attempt
limit; wait for its 15-minute window or start a fresh disposable fixture rather
than weakening production authentication settings.

For documentation captures, use the same UI with synthetic accounts and mail.
Capture only the page, not browser chrome or desktop windows. Review images for
addresses, subjects, tokens, credentials and machine paths before moving them to
`docs/images/`. Use descriptive filenames (`inbox.png`, `accounts.png`), no dated
archives, and strip text/EXIF metadata. Keep only screenshots that explain a
current feature. Replacing an image must not preserve obsolete screenshots in
the documentation tree. The docs check validates PNG metadata and local links.

### Disposable HTTPS installation

The deployment browser snippets mutate data and require an otherwise empty test
installation with only its first ADMIN. Put disposable credentials in a gitignored
JSON file with keys `admin`, `admin_password`, `user_password`, `changed_password`,
and `reset_password`. Never use real operator credentials: MCP traces can expose
input values.

```sh
python tools/render_browser_tests.py .local/test-credentials.json \
  --base-url https://inbox.example.com --mail-domain inbox.example.com
```

Replace example hostnames with your authorized test host. Rendered snippets go to
`.local/`; screenshots/downloads default to `.local/` relative to the MCP workspace.
Use `--artifacts-dir` when the browser tool runs elsewhere.

Execute in order:

1. `.local/browser-accounts.js` creates `browser-user` and `browser-admin`.
2. Run the SMTP helper below for `browser-user` and the first admin. It sends two
   fixture messages per recipient and checks STARTTLS, certificate validation,
   disabled AUTH, unknown recipients and relay rejection.
3. `.local/browser-inbox.js` reads mail and deletes one user message.
4. `.local/browser-admin.js` edits roles/quotas, exports, resets the user password,
   deletes the extra admin, and checks final-admin protection.
5. Run the helper with `--large` for the first admin only; it also sends its two
   normal fixture messages. This scenario requires the default 25 MiB message limit.
6. `.local/browser-security.js` checks reset login, cookie/CSRF controls, admin
   mailbox isolation and bounded display of the maximum-size message.

```sh
python tools/smoke_smtp.py inbox.example.com browser-user@inbox.example.com admin@inbox.example.com
python tools/smoke_smtp.py inbox.example.com admin@inbox.example.com --large
```

Substitute the actual first-admin address. This helper requires trusted STARTTLS
and is not for the plaintext local preview. Run it from an independent network
for external-delivery coverage. A timeout from one origin does not establish an
inbound block; inspect source restrictions, listener state, and target packet arrival.

## Native installer and release checks

Use an authorized disposable Ubuntu 26.04 VM, never a production mailbox host.
Review [installation](docs/installation.md) first. In addition to pytest:

- Check shell syntax with `bash -n install.sh`; use `shellcheck -x install.sh`
  when ShellCheck is available on the Linux host.
- Exercise source and downloaded-archive modes, DNS errors, listener conflicts,
  initial admin setup, shared nginx integration, and local/external HTTPS/SMTP.
- Check service-account file access and owned systemd units with
  `systemd-analyze verify`; confirm unrelated services/configuration remain intact.
- Exercise shared-site attach/detach, validation rollback, changed-marker refusal,
  and preservation of unrelated locations and operator edits. The shared-site
  helper handles explicit simple server blocks; unsupported routing must fail
  safely rather than widening what the parser assumes it understands.
- Exercise certificate refresh/renewal on a test lineage; do not repeatedly request
  production certificates just to test a script.
- Test CLI recovery/export, repeated-install refusal, and confirmed uninstall.
  Check the resulting archive and verify only application-owned resources are removed.
- Record which platform, TLS mode, and network paths were actually exercised in
  review results; do not imply untested combinations work.

Build the distributable from the checkout:

```sh
python tools/build_release.py
```

The output is `dist/inbound-mail-0.1.0.tar.gz` and its `.sha256` file. The archive
contains runtime code, installation files, README, this guide, and `docs/`;
development tools/tests remain in the source checkout. Tar entries normalize
filesystem owner metadata and timestamps. Dependencies are downloaded at install
time; this is not an offline installer.

Before publishing, verify version agreement between `pyproject.toml`,
`mailserver/__init__.py`, and the release filename; run tests and docs checks;
inspect the actual archive and Git history for private material. Publish only
intended Git content and release artifacts, never a workspace ZIP containing
ignored `.local/` data. The default installer downloads source from the public
repository's `master` branch, pinned to the commit resolved by the GitHub API.
It does not consume the built release archive; `--source` accepts a checkout or
extracted release for controlled testing. There is no automatic publishing step
in the tools. Select distribution permissions/license explicitly;
do not imply a license that has not been added.

## Change checklist

- Preserve inbound-only behavior, durable acceptance, authorization and safe MIME rendering.
- Add regression tests for changed behavior; do not introduce speculative abstractions.
- Keep source, packaged assets, installer, documentation and screenshots consistent.
- Remove obsolete documentation instead of preserving a chronological explanation.
- Keep configuration secrets, exports, screenshots of real mail, local hostnames,
  IP addresses and machine-specific paths out of source, artifacts and Git history.
- Keep infrastructure edits separate from local development; get authorization
  before touching shared services, routing or user data.

Useful upstream references: [Django](https://docs.djangoproject.com/en/5.2/),
[aiosmtpd](https://aiosmtpd.aio-libs.org/en/latest/handlers.html),
[nh3](https://nh3.readthedocs.io/en/latest/),
[Gunicorn](https://gunicorn.org/reference/settings/), and
[Certbot](https://eff-certbot.readthedocs.io/en/stable/using.html).
