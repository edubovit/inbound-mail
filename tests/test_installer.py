import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "install.sh").read_text()


@pytest.fixture
def bash():
    executable = shutil.which("bash")
    if not executable and os.name == "nt" and shutil.which("git"):
        candidate = Path(shutil.which("git")).resolve().parents[1] / "bin/bash.exe"
        if candidate.is_file():
            executable = str(candidate)
    if not executable:
        pytest.skip("Bash is required for installer tests")
    return executable


def test_complete_script_parses_and_pipe_help_does_not_install(bash):
    subprocess.run([bash, "-n"], input=SCRIPT, text=True, check=True)
    result = subprocess.run([bash, "-s", "--", "--help"], input=SCRIPT, text=True, capture_output=True, check=True)
    assert "Usage:" in result.stdout
    assert "Prompts always read from /dev/tty" in result.stdout
    assert SCRIPT.rstrip().endswith('main "$@"')
    assert 'exec </dev/tty' in SCRIPT


@pytest.mark.parametrize("mode", ["success", "invalid_revision", "failed_download", "wrong_archive"])
def test_automatic_source_download(bash, tmp_path, mode):
    revision = "a" * 40
    (tmp_path / "commit.json.fixture").write_text(json.dumps({"sha": revision if mode != "invalid_revision" else "../bad"}))
    with tarfile.open(tmp_path / "archive.fixture", "w:gz") as archive:
        prefix = f"inbound-mail-{revision}" if mode != "wrong_archive" else "wrong"
        for name in ["pyproject.toml", "install.sh", "mailserver/__init__.py"]:
            info = tarfile.TarInfo(f"{prefix}/{name}")
            info.size = 4
            archive.addfile(info, io.BytesIO(b"test"))
    downloader = tmp_path / "download.py"
    downloader.write_text('''import pathlib, shutil, sys
args = sys.argv[1:]
destination = pathlib.Path(args[args.index('--output') + 1])
root = destination.parent
url = args[-1]
assert '--proto-redir' in args and '=https' in args
if url.endswith('/commits/master'):
    shutil.copy(root / 'commit.json.fixture', destination)
else:
    assert url.endswith('/tar.gz/' + 'a' * 40), url
    if (root / 'fail').exists():
        raise SystemExit(22)
    shutil.copy(root / 'archive.fixture', destination)
''')
    if mode == "failed_download":
        (tmp_path / "fail").touch()
    start = SCRIPT.index("    command -v curl >/dev/null || die 'Install curl first'")
    end = SCRIPT.index('\nfi\n\ninstall -d -m 750 "$CONF"', start)
    block = SCRIPT[start:end]
    program = f'''set -Eeuo pipefail
WORK='{tmp_path.as_posix()}'
die() {{ echo "$*" >&2; exit 1; }}
python3() {{ '{Path(sys.executable).as_posix()}' "$@"; }}
curl() {{ python3 '{downloader.as_posix()}' "$@"; }}
{block}
test -f "$SOURCE/mailserver/__init__.py"
'''
    result = subprocess.run([bash, "-s"], input=program, text=True, capture_output=True, check=False)
    if mode == "success":
        assert result.returncode == 0, result.stdout + result.stderr
        assert revision in result.stdout
    else:
        assert result.returncode != 0
    if mode == "invalid_revision":
        assert "invalid commit ID" in result.stderr
        assert not (tmp_path / "release.tar.gz").exists()
    assert "ask RELEASE_URL" not in SCRIPT and "ask SHA256" not in SCRIPT
