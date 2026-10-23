import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mailserver.models import Account
from mailserver.storage import deliver

pytestmark = pytest.mark.django_db


def test_login_and_authenticated_shell_are_distinct(client, alice):
    response = client.get('/login/')
    assert b'login-layout' in response.content and b'login-card' in response.content
    assert b'index-rail' not in response.content
    client.force_login(alice)
    response = client.get('/')
    assert b'index-rail' in response.content
    assert b'aria-current="page"' in response.content
    assert b'>Accounts</a>' not in response.content


def test_navigation_and_mail_use_decorative_icons_not_counters(client, admin, raw):
    deliver([admin.address], raw)
    client.force_login(admin)
    html = client.get('/').content.decode()
    nav = re.search(r'<nav class="main-nav".*?</nav>', html, re.S).group()
    assert nav.count('class="nav-icon"') == 3
    assert nav.count('aria-hidden="true" focusable="false"') == 3
    assert not re.search(r'>0[123]<', nav)
    fragment = client.get('/inbox/updates/').content.decode()
    assert 'class="mail-icon"' in fragment
    assert 'class="tile-index"' not in fragment
    assert '>Unread</span>' in fragment


def test_tiles_keep_order_and_destination_when_read_state_changes(client, alice, raw):
    deliver([alice.address], raw)
    deliver([alice.address], raw)
    client.force_login(alice)
    items = list(alice.mail.order_by('-id'))
    before = client.get('/inbox/updates/').content
    items[0].is_read = True
    items[0].save(update_fields=['is_read'])
    after = client.get('/inbox/updates/').content
    for html in [before, after]:
        assert html.index(f'data-message-id="{items[0].pk}"'.encode()) < html.index(f'data-message-id="{items[1].pk}"'.encode())
        assert f'class="tile-link mail-row" href="/messages/{items[0].pk}/"'.encode() in html
    assert b'>Read</span>' in after
    assert b'class="mail-list"' in after
    assert b'entity-grid mail-list' not in after


def test_add_account_action_is_after_collection(client, admin):
    client.force_login(admin)
    html = client.get('/admin/').content
    assert html.index(b'class="add-row"') > html.index(b'</section>', html.index(b'class="entity-grid account-grid"'))


def test_forms_keep_native_select_fallback_and_cancel(client, admin):
    client.force_login(admin)
    response = client.get('/admin/create/')
    assert b'<select name="role"' in response.content
    assert b'/assets/select.js' in response.content
    assert b'class="button secondary" href="/admin/">Cancel' in response.content
    invalid = client.post('/admin/create/', {'username': 'bad/name', 'role': 'ADMIN', 'quota_mib': 10, 'password': 'temporary-passphrase-238!'})
    assert b'has-error' in invalid.content
    assert b'aria-invalid="true"' in invalid.content
    assert b'value="ADMIN" selected' in invalid.content


def test_destructive_confirmation_keeps_account_until_post(client, admin, alice):
    client.force_login(admin)
    response = client.get(f'/admin/accounts/{alice.pk}/delete/')
    assert b'destructive-panel' in response.content
    assert f'href="/admin/accounts/{alice.pk}/">Cancel'.encode() in response.content
    assert Account.objects.filter(pk=alice.pk).exists()


def test_password_gate_allows_only_needed_ui_assets(client, alice):
    alice.must_change_password = True
    alice.save()
    client.force_login(alice)
    response = client.get('/assets/select.js')
    assert response.status_code == 200
    response.close()
    assert client.get('/admin/').url == '/password/'
    for path in ['/favicon.ico', '/assets/favicon.svg']:
        response = client.get(path)
        assert response.status_code == 200
        response.close()


def test_favicon_formats_and_content_security(client, alice, raw):
    login = client.get('/login/')
    assert b'rel="icon" href="/favicon.ico"' in login.content
    assert b'rel="icon" href="/assets/favicon.svg"' in login.content
    assert "img-src 'self'" in login['Content-Security-Policy']
    response = client.get('/favicon.ico')
    assert response['Content-Type'] == 'image/x-icon'
    data = b''.join(response.streaming_content)
    assert struct.unpack('<HHH', data[:6]) == (0, 1, 3)
    for index, size in enumerate([16, 32, 48]):
        width, height, _, _, planes, bits, length, offset = struct.unpack_from('<BBBBHHII', data, 6 + index * 16)
        assert (width, height, planes, bits) == (size, size, 1, 32)
        assert data[offset:offset + 8] == b'\x89PNG\r\n\x1a\n'
        assert offset + length <= len(data)
    response = client.get('/assets/favicon.svg')
    assert response['Content-Type'] == 'image/svg+xml'
    assert ET.fromstring(b''.join(response.streaming_content)).tag.endswith('svg')
    deliver([alice.address], raw)
    client.force_login(alice)
    html = client.get(f'/messages/{alice.mail.get().pk}/html/')
    assert "img-src" not in html['Content-Security-Policy']
    assert "default-src 'none'" in html['Content-Security-Policy']


def test_permission_and_missing_pages_keep_dark_shell(client, alice):
    client.force_login(alice)
    for path, status in [('/admin/', 403), ('/messages/999999/', 404)]:
        response = client.get(path)
        assert response.status_code == status
        assert b'swiss-after-dark' in response.content
        assert b'Return to inbox' in response.content


def test_design_text_contrast_and_flat_surfaces():
    css = (Path(__file__).resolve().parents[1] / 'mailserver/static/style.css').read_text(encoding='utf-8')
    tokens = dict(re.findall(r'(--sad-[\w-]+):\s*(#[0-9a-f]{6});', css))

    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    for text, surface in [
        ('text', 'bg'), ('muted', 'surface'), ('index', 'surface'),
        ('primary-text', 'primary-bg'), ('error-text', 'failure-bg'),
        ('menu-selected-text', 'menu-selected-bg'), ('text', 'menu-active-bg'),
        ('placeholder', 'input-bg'),
    ]:
        light, dark = sorted((luminance(tokens['--sad-' + text]), luminance(tokens['--sad-' + surface])), reverse=True)
        assert (light + 0.05) / (dark + 0.05) >= 4.5, (text, surface)
    assert 'gradient(' not in css
    assert 'translate(' not in css and 'scale(' not in css
    assert '@media (hover: hover)' in css
    assert '@media (prefers-reduced-motion: no-preference)' in css
