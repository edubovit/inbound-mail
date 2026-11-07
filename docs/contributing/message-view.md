# Message rendering

[Developer guide](../../CONTRIBUTING.md) · [Security](../security.md)

`mime.body` decodes the selected MIME body without truncation or filtering.
Unknown charsets use UTF-8 replacement decoding. Django escapes plain text;
HTML-only messages show escaped source so links and text are not silently lost.

The message GET never embeds HTML. A CSRF-protected POST with `view=full` renders
the iframe. Returning via GET restores text; no account/session preference is
stored. Viewing either mode leaves read state unchanged. Both message endpoints
use the current account's ownership check, including for administrators.

`mime.full_html` resolves image Content-IDs to data URLs, removes sender base/meta
tags and rewrites links to new tabs with `noopener noreferrer`. This is not an
HTML sanitizer. Security relies on both the iframe sandbox and the HTML response
CSP: neither grants scripts, same-origin access, forms or top navigation. Only
images, CSS and fonts may load externally, after the user accepts tracking risk.
Do not add `allow-scripts` or `allow-same-origin` to make a sender feature work.
The HTML response sets `Referrer-Policy: no-referrer`; middleware must preserve it.
Stored MIME and attachment downloads remain unchanged.

Run `python -m pytest` for untruncated text, HTML-only fallback, CID rewriting,
explicit choice/CSRF, policy and owner isolation. Run
`python -m tools.check_message_view` with Playwright and its browser engines
installed for an isolated browser check. It creates only synthetic local data,
intercepts remote fixture resources and stops its loopback server afterward.
Browser checks must prove that no image requests occur before consent, images
and styles render afterward, links open without an opener, scripts/forms cannot
run and revisiting a message defaults to text. Markup-only tests cannot prove
that the browser enforces isolation.
