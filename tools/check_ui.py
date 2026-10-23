import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8000"
PASSWORD = "Local-preview-only-248!"
OUTPUT = Path(".local/ui-checks")


def login(page, username="previewadmin", password=PASSWORD):
    page.goto(BASE + "/login/")
    page.get_by_label("Username or email").fill(username)
    page.get_by_label("Password:", exact=True).fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()


def no_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), page.url


def geometry(page):
    return page.locator(".mail-tile").evaluate_all("tiles => tiles.map(tile => {const r=tile.getBoundingClientRect(); return [tile.dataset.messageId,r.x,r.y,r.width,r.height];})")


def choose(page, value):
    page.get_by_role("combobox", name="Role:", exact=True).click()
    page.get_by_role("option", name=value, exact=True).click()


def check_select(page):
    trigger = page.get_by_role("combobox", name="Role:", exact=True)
    expect(trigger).to_be_visible()
    trigger.focus()
    trigger.press("ArrowDown")
    expect(trigger).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_role("option", name="USER", exact=True)).to_have_attribute("aria-selected", "true")
    trigger.press("End")
    trigger.press("Enter")
    expect(trigger).to_have_text("ADMIN")
    trigger.press("Space")
    trigger.press("Home")
    trigger.press("Escape")
    expect(trigger).to_have_text("ADMIN")
    expect(trigger).to_have_attribute("aria-expanded", "false")
    trigger.press("ArrowUp")
    trigger.press("Home")
    trigger.press("Enter")
    expect(trigger).to_have_text("USER")
    trigger.press("a")
    trigger.press("Enter")
    expect(trigger).to_have_text("ADMIN")
    trigger.click()
    page.get_by_role("option", name="USER", exact=True).click()
    expect(trigger).to_have_text("USER")
    trigger.click()
    trigger.press("Tab")
    expect(trigger).to_have_attribute("aria-expanded", "false")
    trigger.click()
    page.locator("h1").click()
    expect(trigger).to_have_attribute("aria-expanded", "false")
    page.locator("select[name=role]").evaluate("el => {el.value='ADMIN'; el.dispatchEvent(new Event('change',{bubbles:true}));}")
    expect(trigger).to_have_text("ADMIN")
    page.locator("form.editor-form").evaluate("form => form.reset()")
    expect(trigger).to_have_text("USER")
    page.set_viewport_size({"width": 320, "height": 400})
    trigger.scroll_into_view_if_needed()
    trigger.click()
    menu = page.get_by_role("listbox")
    expect(menu).to_be_visible()
    bounds = menu.bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 320
    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= 400
    expect(menu).to_have_css("background-color", "rgb(32, 32, 30)")
    page.get_by_role("option", name="ADMIN", exact=True).hover()
    expect(page.get_by_role("option", name="ADMIN", exact=True)).to_have_css("background-color", "rgb(64, 53, 46)")
    trigger.press("Escape")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.evaluate("""() => {
      const div=document.createElement('div');
      const label=document.createElement('label'); label.htmlFor='dynamic'; label.textContent='Dynamic role';
      const select=document.createElement('select'); select.id='dynamic';
      for (const name of ['USER','ADMIN']) {const option=document.createElement('option');option.value=name;option.textContent=name;select.append(option);}
      div.append(label,select);document.querySelector('.form-fields').append(div);
    }""")
    dynamic = page.get_by_role("combobox", name="Dynamic role", exact=True)
    expect(dynamic).to_be_visible()
    dynamic.click()
    page.get_by_role("option", name="ADMIN", exact=True).click()
    expect(dynamic).to_have_text("ADMIN")
    page.locator("#dynamic").evaluate("el => el.parentElement.remove()")


def check_engine(browser_type):
    browser = browser_type.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="light")
    page = context.new_page()
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    result = {"engine": browser_type.name, "version": browser.version}
    try:
        page.goto(BASE + "/login/")
        for selector in [".login-intro h1", ".login-card h2", "label", "input", ".login-card button"]:
            assert page.locator(selector).first.evaluate("el => getComputedStyle(el).fontFamily").startswith("Arial")
        expect(page.locator("body")).to_have_css("background-color", "rgb(20, 20, 20)")
        if browser_type.name == "chromium":
            session = context.new_cdp_session(page)
            session.send("DOM.enable")
            session.send("CSS.enable")
            root = session.send("DOM.getDocument")["root"]["nodeId"]
            node = session.send("DOM.querySelector", {"nodeId": root, "selector": ".login-intro h1"})["nodeId"]
            result["login_fonts"] = [font["familyName"] for font in session.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]]
            assert "Arial" in result["login_fonts"]
        for width in [1440, 768, 390, 320]:
            page.set_viewport_size({"width": width, "height": 900})
            no_overflow(page)
        page.set_viewport_size({"width": 1440, "height": 1000})
        login(page)
        expect(page.locator("h1")).to_have_text("Inbox")
        expect(page.locator('.main-nav .nav-icon')).to_have_count(3)
        expect(page.locator('.main-nav .nav-index, .mail-list .tile-index')).to_have_count(0)
        assert page.locator('.mail-icon svg[aria-hidden="true"][focusable="false"]').count() > 0
        for width in [1440, 768, 390, 320]:
            page.set_viewport_size({"width": width, "height": 900})
            no_overflow(page)
            columns = page.locator(".mail-list").evaluate("el=>getComputedStyle(el).gridTemplateColumns.split(' ').length")
            assert columns == 1
            rail = page.locator(".index-rail")
            expect(rail).to_have_css("border-bottom-width" if width <= 800 else "border-right-width", "3px")
            page.screenshot(path=str(OUTPUT / f"{browser_type.name}-inbox-{width}.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        before = geometry(page)
        tile = page.locator(".mail-tile").first
        tile.hover()
        expect(tile).to_have_css("background-color", "rgb(40, 40, 38)")
        assert geometry(page) == before
        expect(tile.locator("a")).to_have_css("text-decoration-line", "none")
        page.mouse.move(0, 0)
        tile.locator("a").focus()
        expect(tile).to_have_css("outline-width", "2px")
        assert geometry(page) == before
        message_path = tile.locator("a").get_attribute("href")
        page.keyboard.press("Enter")
        page.wait_for_url(BASE + message_path)
        page.goto(BASE)
        page.evaluate("window.scrollTo(0,0)")
        before = geometry(page)
        token = page.locator('input[name="csrfmiddlewaretoken"]').first.input_value()
        for read in ["yes", "no"]:
            page.request.post(BASE + message_path + "read/", form={"csrfmiddlewaretoken": token, "read": read}, headers={"Origin": BASE})
            page.get_by_role("link", name="Refresh", exact=True).click()
            expect(page.locator(".mail-tile").first.locator(".read-state")).to_have_text("Read" if read == "yes" else "Unread")
            assert geometry(page) == before
        tile = page.locator(".mail-tile").first
        bounds = tile.bounding_box()
        page.mouse.click(bounds["x"] + bounds["width"] - 10, bounds["y"] + bounds["height"] - 10)
        page.wait_for_url(BASE + message_path)
        page.goto(BASE)
        page.locator('.mail-row').filter(has_text='Notes from the infrastructure review').click()
        page.get_by_text("Safe HTML view", exact=True).click()
        frame = page.frame_locator('iframe[title="Email HTML"]')
        expect(frame.get_by_role('heading', name='Infrastructure review')).to_be_visible()
        expect(frame.locator('body')).to_have_css('background-color', 'rgb(25, 25, 25)')
        assert frame.locator('body script,body img,body [href],body [src]').count() == 0
        with page.expect_download() as event:
            page.get_by_role('link', name='review.txt', exact=True).click()
        assert Path(event.value.path()).read_bytes() == b'Review complete.\n'
        for width in [768, 390, 320]:
            page.set_viewport_size({"width": width, "height": 650})
            no_overflow(page)
        page.goto(BASE + '/admin/')
        for width in [1440, 768, 390, 320]:
            page.set_viewport_size({"width": width, "height": 900})
            no_overflow(page)
            assert page.locator('.account-grid').evaluate("el=>getComputedStyle(el).gridTemplateColumns.split(' ').length") == (1 if width <= 600 else 2)
            grid = page.locator('.account-grid').bounding_box()
            add = page.locator('.add-row').bounding_box()
            assert abs(add['x'] - grid['x']) < 1
            assert abs(add['y'] - grid['y'] - grid['height'] - 16) < 1
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role('link', name='Create account', exact=True).click()
        check_select(page)
        username = ('ui-' + browser_type.name + '-').ljust(64, 'x')
        page.get_by_label('Username:', exact=True).fill(username)
        choose(page, 'ADMIN')
        page.get_by_label('Mailbox quota (MiB)').fill('4')
        page.get_by_label('Temporary password').fill('Browser-temporary-581!')
        page.get_by_role('button', name='Create account', exact=True).click()
        expect(page.locator('h1')).to_have_text('Accounts')
        page.get_by_role('link', name=username + '@mail.test', exact=True).click()
        expect(page.get_by_role('combobox', name='Role:', exact=True)).to_have_text('ADMIN')
        for width in [1440, 768, 390, 320]:
            page.set_viewport_size({'width': width, 'height': 600})
            no_overflow(page)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        choose(page, 'USER')
        page.get_by_role('button', name='Save account', exact=True).click()
        page.get_by_role('link', name=username + '@mail.test', exact=True).click()
        page.get_by_role('link', name='Reset password', exact=True).click()
        page.get_by_label('Temporary password').fill('Browser-reset-248!')
        page.get_by_role('button', name='Reset password', exact=True).click()
        page.get_by_role('link', name='Export all mail', exact=True).click()
        page.get_by_label('I understand and confirm').check()
        with page.expect_download() as export:
            page.get_by_role('button', name='Download archive', exact=True).click()
        assert Path(export.value.path()).stat().st_size > 1024
        page.goto(BASE + '/admin/')
        page.get_by_role('link', name=username + '@mail.test', exact=True).click()
        page.get_by_role('link', name='Delete account', exact=True).click()
        page.get_by_label('I understand and confirm').check()
        page.get_by_role('button', name='Delete account permanently', exact=True).click()
        expect(page.get_by_role('link', name=username + '@mail.test', exact=True)).to_have_count(0)
        page.get_by_role('link', name='Create account', exact=True).click()
        page.get_by_label('Username:', exact=True).fill('bad/name')
        choose(page, 'ADMIN')
        page.get_by_label('Temporary password').fill('Browser-temporary-581!')
        page.get_by_role('button', name='Create account', exact=True).click()
        expect(page.locator('.errorlist')).to_be_visible()
        expect(page.get_by_role('combobox', name='Role:', exact=True)).to_have_text('ADMIN')
        for width in [768, 390, 320]:
            page.set_viewport_size({'width': width, 'height': 400})
            no_overflow(page)
            page.get_by_role('button', name='Create account', exact=True).scroll_into_view_if_needed()
        page.emulate_media(reduced_motion='reduce')
        page.goto(BASE)
        expect(page.locator('.mail-tile').first).to_have_css('transition-duration', '0s')
        page.emulate_media(forced_colors='active')
        page.locator('.tile-link').first.focus()
        expect(page.locator('.mail-tile').first).to_have_css('outline-width', '2px')
        page.emulate_media(forced_colors='none')
        with browser.new_context(storage_state=context.storage_state(), java_script_enabled=False) as fallback:
            tab = fallback.new_page()
            tab.goto(BASE + '/admin/create/')
            native = tab.get_by_label('Role:', exact=True)
            expect(native).to_be_visible()
            native.select_option('ADMIN')
            expect(native).to_have_value('ADMIN')
            assert tab.locator('.select-trigger').count() == 0
        page.locator('.mail-row').first.evaluate("el => el.textContent='VeryLongSubject'.repeat(35)")
        page.set_viewport_size({'width': 320, 'height': 600})
        no_overflow(page)
        page.get_by_role('button', name='Sign out', exact=True).click()
        page.wait_for_url(BASE + '/login/')
        login(page, 'reader', 'Local-reader-only-248!')
        expect(page.get_by_role('heading', name='No messages yet')).to_be_visible()
        expect(page.get_by_role('link', name='Accounts', exact=True)).to_have_count(0)
        assert page.request.get(BASE + '/admin/').status == 403
        assert not errors, errors
        state = context.storage_state()
        result['checks'] = ['four viewport sizes', 'Arial login', 'grid and rail', 'stable hover/read geometry', 'whole tile and keyboard navigation', 'safe HTML', 'attachments', 'custom dropdown interactions and dynamic fields', 'create/edit/reset/export/delete', 'validation persistence', 'empty USER inbox', 'reduced motion', 'forced colors']
        with browser.new_context(storage_state=state, java_script_enabled=False) as plain:
            tab = plain.new_page()
            tab.goto(BASE)
            expect(tab.get_by_text('Enable JavaScript for automatic updates, or use Refresh to check for new mail.', exact=True)).to_be_visible()
            tab.get_by_role('link', name='Refresh', exact=True).click()
            expect(tab.get_by_role('heading', name='No messages yet')).to_be_visible()
        with browser.new_context(has_touch=True, viewport={'width':390,'height':844}) as touch:
            tab = touch.new_page()
            login(tab)
            tile = tab.locator('.mail-tile').first
            target = tile.locator('a').get_attribute('href')
            tile.scroll_into_view_if_needed()
            rect = tile.bounding_box()
            tab.touchscreen.tap(rect['x']+rect['width']-10, rect['y']+rect['height']-10)
            tab.wait_for_url(BASE + target)
            tab.goto(BASE + '/admin/create/')
            tab.get_by_role('combobox',name='Role:',exact=True).tap()
            tab.get_by_role('option',name='ADMIN',exact=True).tap()
            expect(tab.get_by_role('combobox',name='Role:',exact=True)).to_have_text('ADMIN')
        result['checks'].extend(['no-JavaScript inbox and native select fallback', 'long content', 'touch row and dropdown'])
        return result
    finally:
        context.close()
        browser.close()


def main():
    parser = argparse.ArgumentParser(description='Run browser checks against the isolated local preview, never a deployed host')
    parser.add_argument('--engines', nargs='+', choices=['chromium','firefox','webkit'], default=['chromium','firefox','webkit'])
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        for engine in args.engines:
            result = check_engine(getattr(playwright, engine))
            results.append(result)
            print(json.dumps(result), flush=True)
            (OUTPUT / 'results.json').write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
