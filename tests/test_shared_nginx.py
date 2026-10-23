import json
from unittest.mock import patch

import pytest

from deploy import shared_nginx as shared

SITE = '''map $http_upgrade $upgrade { default upgrade; '' close; }
server {
    listen 20443 ssl;
    listen [::]:20443 ssl;
    server_name inbox.example.com;
    ssl_certificate /existing/cert.pem;
    ssl_certificate_key /existing/key.pem;
    location = /monitoring { return 308 /monitoring/; }
    location ^~ /monitoring/ { proxy_pass http://127.0.0.1:20001; }
}
'''


def test_add_include_preserves_every_original_byte():
    updated, marker = shared.insertion(SITE, "inbox.example.com", 20443, shared.SNIPPET)
    assert updated.replace(marker, "") == SITE
    assert updated.count(str(shared.SNIPPET)) == 1
    assert "location ^~ /monitoring/" in updated
    assert "client_max_body_size 64k" in shared.root_location(20025)


@pytest.mark.parametrize("directive", [
    "location / { return 200; }", "location = / { return 200; }",
    "location ^~ / { return 200; }", "location ~ /admin { return 200; }",
    "location /assets/ { return 200; }", "include other.conf;", "return 301 /monitoring/;",
    "rewrite ^ /monitoring/;", "error_page 404 /monitoring/;",
])
def test_refuses_ambiguous_or_overlapping_routes(directive):
    text = SITE.replace("    server_name", directive + "\n    server_name")
    with pytest.raises(ValueError):
        shared.insertion(text, "inbox.example.com", 20443, shared.SNIPPET)


def test_requires_one_exact_server_and_tls_listener():
    for text, hostname, port in [(SITE, "other.example.com", 20443), (SITE, "inbox.example.com", 443),
                                 (SITE + SITE, "inbox.example.com", 20443),
                                 (SITE.replace(" ssl", ""), "inbox.example.com", 20443),
                                 (SITE.replace("server_name inbox.example.com", "server_name inbox.example.com other.example.com"), "inbox.example.com", 20443)]:
        with pytest.raises(ValueError):
            shared.insertion(text, hostname, port, shared.SNIPPET)


def test_comments_quotes_and_other_server_do_not_confuse_selection():
    text = '# server { location / {} }\n' + SITE.replace("server_name inbox.example.com", 'server_name "inbox.example.com"')
    text += 'server { listen 8080; server_name other.example.com; location / { return 200 "}"; } }'
    updated, marker = shared.insertion(text, "inbox.example.com", 20443, shared.SNIPPET)
    assert updated.replace(marker, "") == text


@pytest.fixture
def integration(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(shared, "SNIPPET", tmp_path / "snippet.conf")
    site = tmp_path / "site.conf"
    site.write_text(SITE)
    return site


def test_attach_detach_preserves_operator_edits(integration):
    with patch.object(shared, "validate"), patch.object(shared.subprocess, "run") as command:
        shared.attach(integration, "inbox.example.com", 20443, 20025)
        assert shared.STATE.exists() and shared.SNIPPET.exists()
        integration.write_bytes(integration.read_bytes().replace(b"20001", b"20003"))
        shared.detach()
        command.assert_called_once_with(["systemctl", "reload", "nginx"], check=True)
    assert integration.read_text() == SITE.replace("20001", "20003")
    assert not shared.STATE.exists() and not shared.SNIPPET.exists()


def test_invalid_candidate_restores_original(integration):
    with patch.object(shared, "validate", side_effect=[None, ValueError("bad config")]):
        with pytest.raises(ValueError, match="bad config"):
            shared.attach(integration, "inbox.example.com", 20443, 20025)
    assert integration.read_text() == SITE
    assert not shared.STATE.exists() and not shared.SNIPPET.exists()


def test_detach_failure_keeps_include_and_state(integration):
    with patch.object(shared, "validate"):
        shared.attach(integration, "inbox.example.com", 20443, 20025)
    current = integration.read_text()
    with patch.object(shared, "validate", side_effect=ValueError("bad config")):
        with pytest.raises(ValueError):
            shared.detach()
    assert integration.read_text() == current and shared.STATE.exists() and shared.SNIPPET.exists()


def test_modified_marker_refuses_cleanup(integration):
    with patch.object(shared, "validate"):
        shared.attach(integration, "inbox.example.com", 20443, 20025)
    marker = json.loads(shared.STATE.read_text())["marker"]
    integration.write_text(integration.read_text().replace(marker, ""))
    with pytest.raises(ValueError, match="edited or removed"):
        shared.detach()
    assert shared.STATE.exists() and shared.SNIPPET.exists()


def test_nginx_warnings_are_failure():
    with patch.object(shared.subprocess, "run") as command:
        command.return_value.returncode = 0
        command.return_value.stdout = ""
        command.return_value.stderr = 'conflicting server name "inbox.example.com"'
        with pytest.raises(ValueError):
            shared.validate()


def test_round_trip_preserves_crlf_bytes(integration):
    original = SITE.replace("\n", "\r\n").encode()
    integration.write_bytes(original)
    with patch.object(shared, "validate"), patch.object(shared.subprocess, "run"):
        shared.attach(integration, "inbox.example.com", 20443, 20025)
        shared.detach()
    assert integration.read_bytes() == original
