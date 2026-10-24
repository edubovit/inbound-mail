# Security and limits

[User guide](../README.md) · [Operations](operations.md) · [Development](../CONTRIBUTING.md)

## Trust and privacy

Inbound is for private, admin-managed mailboxes, not an anonymous public mail
service. USER and ADMIN can browse only their own inboxes. ADMIN can manage all
accounts and export all stored mail, so users have no mail confidentiality from
admins or server operators. There is no end-to-end or application-level disk
encryption. Use host/storage encryption where required.

Root-only account archives contain password hashes and can create privileged
accounts when imported. They are unencrypted credential material, not mail
archives. Upgrade rollback directories also contain mail, configuration secrets
and private keys; retain root-only access and manage their lifetime explicitly.

Accounts have no compose, reply, forward, SMTP submission, IMAP, or POP3 service.
The SMTP listener accepts only known recipients at the configured domain and
does not offer AUTH. It has no outbound mail path or delivery queue. Errors are
returned to the sending SMTP client; Inbound never sends bounces or alerts.

## Browser controls

- Password hashes, server-side authorization, CSRF protection, and database sessions.
- Production HTTPS enforcement, Secure cookies, HttpOnly session cookies,
  SameSite=Strict sessions, and 12-hour session expiry.
- Password resets invalidate sessions. The UI requires a password change; the
  scripted CLI defaults to this too but can explicitly provision a final password.
- Login limits: 10 attempts per username and 30 per source IP in 15 minutes.
- UI scripts/styles and fetch requests are same-origin under CSP; pages are not
  embeddable by external sites and responses use `Cache-Control: no-store`.
- HSTS applies to the UI hostname, not all subdomains; preload is not enabled.

Password-strength checks are disabled across web forms, CLI account commands and
installation. Short, common, entirely numeric, or username-matching passwords are
accepted, increasing account-takeover risk. Passwords remain required and hashed;
password changes still check the old password and matching confirmation. Existing
input-size limits and login throttles remain in place, but are not a substitute
for strong passwords.

Only a loopback proxy connection may supply a login-rate-limit client IP through
`X-Real-IP`. The installed nginx site overwrites forwarding headers. Keep the
application listener private and do not trust arbitrary client proxy headers.

## Untrusted mail

HTML is sanitized by an allowlist and rendered in a sandboxed iframe with its
own restrictive CSP. Email scripts, styles, images, form controls, and active
links are removed. The application supplies its own dark stylesheet. Plain text
and headers are escaped; body previews are capped at 1 MiB of decoded content.
Original bytes remain available in exports.

Attachments are downloaded as files with sanitized filenames and are **not
scanned for malware**. HTML sanitization does not make arbitrary attachments safe.
No SPF/DKIM verification, spam scoring, or antivirus engine is included.

## Availability and delivery

Production offers SMTP STARTTLS with TLS 1.2+, but plaintext reception is allowed
for compatibility. HTTPS requires TLS 1.2+. Neither guarantees encryption across
every preceding hop between sender and recipient.

Size, rate, connection, recipient, mailbox, and disk-reserve limits reduce abuse;
they are not denial-of-service protection. Only one DATA transfer is handled at
a time to bound message-buffer memory. Rate limits can delay legitimate shared
senders. Configure and monitor the [limits](configuration.md) for your workload.

SMTP success follows a durable SQLite commit, with recipient/quota checks in the
same transaction. If the connection fails after commit but before the sender
receives success, a retry can create a duplicate. There is no deduplication
guarantee. Database/storage loss still requires operator recovery; mail exports
have no application restore path. Account-only imports do not restore messages.

Deletion uses SQLite secure-delete and auto-vacuum settings but cannot erase
copies in exports, filesystem snapshots, SSD firmware, or provider backups.

Do not publish message contents, production configuration, private keys, sessions,
exports, or logs in bug reports. Use synthetic mail and sanitized reproduction
steps. Fixed development secrets and preview passwords are for loopback-only
testing and must never be used for a public deployment.
