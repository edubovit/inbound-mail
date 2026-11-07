import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path

BASE = "http://127.0.0.1:8017"
IMAGE = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==")


def seed():
    os.environ["DJANGO_SETTINGS_MODULE"] = "mailserver.settings"
    import django

    django.setup()
    from mailserver.cli import initialize
    from mailserver.storage import deliver

    initialize("preview", "preview")
    message = EmailMessage()
    message["Subject"] = "Full view fixture"
    message.set_content("Complete plain text https://example.org/link <not markup>\n" + "x" * (1024 * 1024 + 1) + " END OF BODY")
    message.add_alternative('''<!doctype html><html><head>
<meta http-equiv="refresh" content="0;url=https://example.org/redirect">
<link rel="stylesheet" href="https://example.org/theme.css">
<style>body {background: rgb(245, 240, 230); color: rgb(20, 20, 20)} h1 {color: rgb(120, 30, 20)}</style>
</head><body><h1>Full message</h1>
<a href="https://example.org/link" target="_top">Original link</a>
<img alt="Remote image" src="https://example.org/pixel">
<img alt="Embedded image" src="cid:picture@mail">
<script>window.executed = true; parent.hacked = true; fetch('https://example.org/script')</script>
<script src="https://example.org/script.js"></script>
<img src="https://example.org/broken" onerror="window.executed=true">
<form action="https://example.org/form"><input name="secret" value="fixture"><button>Submit email form</button></form>
<iframe src="https://example.org/nested"></iframe>
</body></html>''', subtype="html")
    message.get_payload()[1].add_related(IMAGE, maintype="image", subtype="png", cid="<picture@mail>")
    deliver(["preview@mail.test"], message.as_bytes())


def verify(engine, browser_type):
    from playwright.sync_api import expect

    browser = browser_type.launch()
    try:
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        requests = []

        def remote(route):
            requests.append(route.request.url)
            if route.request.url.endswith("/pixel"):
                route.fulfill(content_type="image/png", body=IMAGE)
            elif route.request.url.endswith("/theme.css"):
                route.fulfill(content_type="text/css", body="h1 {font-size: 37px}")
            elif route.request.url.endswith("/broken"):
                route.fulfill(status=404, body="missing")
            else:
                route.fulfill(content_type="text/html", body="<h1>External destination</h1>")

        context.route("https://example.org/**", remote)
        page = context.new_page()
        page.goto(BASE + "/login/")
        page.get_by_label("Username or email").fill("preview")
        page.get_by_label("Password:", exact=True).fill("preview")
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.locator(".mail-row").click()
        path = page.url
        expect(page.locator("pre.body")).to_contain_text("END OF BODY")
        expect(page.locator("iframe")).to_have_count(0)
        assert not requests
        page.get_by_role("button", name="Show full view", exact=True).click()
        frame = page.frame_locator('iframe[title="Email HTML"]')
        expect(frame.get_by_role("heading", name="Full message")).to_be_visible()
        expect(frame.locator("h1")).to_have_css("color", "rgb(120, 30, 20)")
        expect(frame.locator("h1")).to_have_css("font-size", "37px")
        for name in ["Remote image", "Embedded image"]:
            expect(frame.get_by_alt_text(name)).to_have_js_property("naturalWidth", 1)
        email_frame = next(f for f in page.frames if "/html/" in f.url)
        assert email_frame.evaluate("window.executed") is None
        assert page.evaluate("window.hacked") is None
        assert email_frame.evaluate("() => {try {return parent.document.title} catch {return 'isolated'}}") == "isolated"
        frame.get_by_role("button", name="Submit email form").click()
        with context.expect_page() as event:
            frame.get_by_role("link", name="Original link").click()
        popup = event.value
        popup.wait_for_load_state()
        assert popup.url == "https://example.org/link"
        assert popup.evaluate("window.opener === null")
        popup.close()
        assert all(url.rsplit("/", 1)[-1] in {"pixel", "broken", "link", "theme.css"} for url in requests), requests
        assert page.url == path
        page.screenshot(path=f".local/full-view-{engine}.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_role("link", name="Show plain text", exact=True).click()
        expect(page.locator("iframe")).to_have_count(0)
        expect(page.locator("pre.body")).to_contain_text("END OF BODY")
        page.set_viewport_size({"width": 1440, "height": 1000})
        before = len(requests)
        page.goto(path)
        expect(page.locator("iframe")).to_have_count(0)
        assert len(requests) == before
        direct = context.new_page()
        direct.goto(path + "html/")
        expect(direct.get_by_role("heading", name="Full message")).to_be_visible()
        assert direct.evaluate("window.executed") is None
        assert direct.evaluate("() => {try {document.cookie; return 'accessible'} catch {return 'isolated'}}") == "isolated"
        direct.close()
        no_js = browser.new_context(java_script_enabled=False, storage_state=context.storage_state())
        fallback = no_js.new_page()
        no_js.route("https://example.org/**", remote)
        fallback.goto(path)
        expect(fallback.locator("iframe")).to_have_count(0)
        fallback.get_by_role("button", name="Show full view", exact=True).click()
        expect(fallback.frame_locator("iframe").get_by_role("heading", name="Full message")).to_be_visible()
        no_js.close()
        return {"engine": engine, "version": browser.version, "passed": True}
    finally:
        browser.close()


def main():
    from playwright.sync_api import sync_playwright

    Path(".local").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="message-view-", dir=".local") as directory:
        env = {**os.environ, "MAIL_DEV_DATA": str(Path(directory).resolve())}
        env.pop("MAIL_CONFIG", None)
        subprocess.run([sys.executable, "-m", "tools.check_message_view", "--seed"], env=env, check=True)
        with open(Path(directory) / "server.log", "w") as log:
            server = subprocess.Popen([sys.executable, "-m", "mailserver.cli", "dev-web", "--port", "8017"], env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("Preview server failed to start")
                    try:
                        with urllib.request.urlopen(BASE + "/health/", timeout=1) as response:
                            if response.read() == b"ok\n":
                                break
                    except urllib.error.URLError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Preview server did not become healthy")
                with sync_playwright() as playwright:
                    results = [verify(name, getattr(playwright, name)) for name in ["chromium", "firefox", "webkit"]]
                print(json.dumps(results))
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    if sys.argv[1:] == ["--seed"]:
        seed()
    else:
        main()
