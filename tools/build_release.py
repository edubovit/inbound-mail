import hashlib
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)
archive = DIST / "inbound-mail-0.1.0.tar.gz"


def public_metadata(info):
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    info.pax_headers = {}
    info.mode = 0o644
    return info


with tarfile.open(archive, "w:gz") as output:
    for name in ["mailserver", "deploy", "install.sh", "pyproject.toml", "requirements.txt", "README.md", "CONTRIBUTING.md", "docs"]:
        path = ROOT / name
        files = sorted(path.rglob("*")) if path.is_dir() else [path]
        for file in files:
            if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                output.add(file, arcname="inbound-mail/" + file.relative_to(ROOT).as_posix(), filter=public_metadata)
with archive.open("rb") as source:
    checksum = hashlib.file_digest(source, "sha256").hexdigest()
archive.with_suffix(archive.suffix + ".sha256").write_text(f"{checksum}  {archive.name}\n")
print(archive.relative_to(ROOT))
print(checksum)
