import re
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
