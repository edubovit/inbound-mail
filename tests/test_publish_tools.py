import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_browser_renderer_uses_explicit_target_and_private_output(tmp_path):
    (tmp_path / "tools").mkdir()
    shutil.copy(ROOT / "tools/render_browser_tests.py", tmp_path / "tools/")
    shutil.copytree(ROOT / "tests", tmp_path / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"admin": "testadmin", "admin_password": "synthetic-test-value"}))
    result = subprocess.run([
        sys.executable, str(tmp_path / "tools/render_browser_tests.py"), str(credentials),
        "--base-url", "https://inbox.example.com/", "--mail-domain", "mail.example.com",
        "--artifacts-dir", "artifacts",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    for name in ["accounts", "admin", "inbox", "security"]:
        script = (tmp_path / f".local/browser-{name}.js").read_text()
        assert "__TEST_CONFIG__" not in script
        assert "__TEST_CREDENTIALS__" not in script
        assert '"base_url": "https://inbox.example.com"' in script
        assert '"mail_domain": "mail.example.com"' in script
        assert '"artifacts_dir": "artifacts"' in script


def test_release_metadata_and_contents_are_portable(tmp_path):
    (tmp_path / "tools").mkdir()
    shutil.copy(ROOT / "tools/build_release.py", tmp_path / "tools/")
    for name in ["mailserver", "deploy", "docs"]:
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ["install.sh", "pyproject.toml", "requirements.txt", "README.md", "CONTRIBUTING.md"]:
        shutil.copy(ROOT / name, tmp_path / name)
    (tmp_path / ".local").mkdir()
    (tmp_path / ".local/private.txt").write_text("synthetic-private-marker")
    subprocess.run([sys.executable, str(tmp_path / "tools/build_release.py")], capture_output=True, check=True)
    with tarfile.open(tmp_path / "dist/inbound-mail-0.1.0.tar.gz") as archive:
        names = archive.getnames()
        assert "inbound-mail/mailserver/static/inbox.js" in names
        assert "inbound-mail/mailserver/static/favicon.svg" in names
        assert "inbound-mail/mailserver/static/favicon.ico" in names
        assert "inbound-mail/deploy/shared_nginx.py" in names
        assert "inbound-mail/CONTRIBUTING.md" in names
        assert "inbound-mail/docs/configuration.md" in names
        assert "inbound-mail/docs/images/inbox.png" in names
        for entry in archive:
            assert entry.name.startswith("inbound-mail/")
            assert ".local" not in entry.name and "__pycache__" not in entry.name
            assert entry.uid == entry.gid == entry.mtime == 0
            assert not entry.uname and not entry.gname
            assert b"synthetic-private-marker" not in archive.extractfile(entry).read()
