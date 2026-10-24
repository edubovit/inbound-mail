import json
import os
import subprocess
import sys

import pytest
from django.contrib.auth.password_validation import get_default_password_validators
from django.test import Client
from django.urls import reverse

from mailserver.cli import main
from mailserver.models import Account

pytestmark = pytest.mark.django_db
PASSWORDS = ['1', '123456789012345', 'password', 'matching-account-name', ' padded ', ' ']


@pytest.mark.parametrize('password', PASSWORDS)
def test_web_create_change_reset_and_login_accept_password_without_strength_rules(client, admin, password):
    assert get_default_password_validators() == []
    client.force_login(admin)
    response = client.post('/admin/create/', {
        'username': 'matching-account-name', 'role': 'USER', 'quota_mib': 1, 'password': password,
    })
    assert response.status_code == 302
    user = Account.objects.get(username='matching-account-name')
    assert user.password != password and user.check_password(password)
    mailbox = Client()
    assert mailbox.post('/login/', {'username': user.username, 'password': password}).url == '/password/'
    form = mailbox.get('/password/').context['form']
    assert not str(form.fields['new_password1'].help_text)
    response = mailbox.post('/password/', {
        'old_password': password, 'new_password1': password, 'new_password2': password,
    })
    assert response.status_code == 302
    user.refresh_from_db()
    assert not user.must_change_password and user.check_password(password)
    mailbox.post('/logout/')
    assert mailbox.post('/login/', {'username': user.username, 'password': password}).url == '/'
    response = client.post(reverse('reset_password', args=[user.pk]), {'password': password})
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.must_change_password and user.check_password(password)
    assert mailbox.get('/').status_code == 302


@pytest.mark.parametrize('password', PASSWORDS)
def test_cli_create_reset_and_admin_recovery_accept_password_without_strength_rules(admin, password, tmp_path, monkeypatch, capsys):
    password_file = tmp_path / 'password'
    password_file.write_bytes((password + '\n').encode())
    password_file.chmod(0o600)
    for arguments, username in [
        (['accounts', 'create', 'matching-account-name'], 'matching-account-name'),
        (['accounts', 'reset-password', 'matching-account-name'], 'matching-account-name'),
        (['reset-admin', 'admin'], 'admin'),
    ]:
        monkeypatch.setattr(sys, 'argv', ['inbound-mail', *arguments, '--password-file', str(password_file)])
        main()
        result = json.loads(capsys.readouterr().out)
        assert result['username'] == username and 'password' not in result
        user = Account.objects.get(username=username)
        assert user.password != password and user.check_password(password)


@pytest.mark.parametrize('old,new,confirmation', [
    ('wrong', '1', '1'),
    ('Alice-passphrase-123!', '1', '2'),
    ('Alice-passphrase-123!', '', ''),
])
def test_password_change_still_checks_old_password_confirmation_and_nonempty(client, alice, old, new, confirmation):
    client.force_login(alice)
    before = alice.password
    response = client.post('/password/', {'old_password': old, 'new_password1': new, 'new_password2': confirmation})
    assert response.status_code == 200 and response.context['form'].errors
    alice.refresh_from_db()
    assert alice.password == before


def test_admin_reset_still_requires_password(client, admin, alice):
    client.force_login(admin)
    before = alice.password
    response = client.post(reverse('reset_password', args=[alice.pk]), {'password': ''})
    assert response.status_code == 200 and response.context['form'].errors
    alice.refresh_from_db()
    assert alice.password == before


def test_initial_admin_accepts_short_password_but_not_empty(tmp_path):
    program = '''from mailserver.cli import setup, initialize
setup()
from django.conf import settings
from django.core.exceptions import ValidationError
from mailserver.models import Account
try:
    initialize('admin', '')
except ValidationError:
    pass
else:
    raise AssertionError('Empty password accepted')
assert not (settings.DATA_DIR / 'mail.sqlite3').exists()
initialize('admin', '1')
user = Account.objects.get(username='admin')
assert user.password.startswith('pbkdf2_sha256$')
assert user.check_password('1')
'''
    env = {**os.environ, 'MAIL_DEV_DATA': str(tmp_path / 'data')}
    env.pop('MAIL_CONFIG', None)
    result = subprocess.run([sys.executable, '-c', program], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
