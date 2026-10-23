import re
import struct
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def headings(text):
    return {
        re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", title.strip().lower()))
        for title in re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
    }


def check_docs(root=ROOT):
    errors = []
    pages = [root / "README.md", root / "CONTRIBUTING.md", *sorted((root / "docs").rglob("*.md"))]
    for page in pages:
        if not page.is_file():
            errors.append(f"Missing document: {page.relative_to(root)}")
            continue
        text = re.sub(r"```.*?```", "", page.read_text(encoding="utf-8"), flags=re.DOTALL)
        for link in re.findall(r"!?\[[^\]]*\]\(([^\s)]+)\)", text):
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            target = (page.parent / unquote(url.path)).resolve() if url.path else page
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                errors.append(f"{page.relative_to(root)}: missing/outside target {link}")
            elif url.fragment and target.suffix == ".md":
                target_text = re.sub(r"```.*?```", "", target.read_text(encoding="utf-8"), flags=re.DOTALL)
                if unquote(url.fragment) not in headings(target_text):
                    errors.append(f"{page.relative_to(root)}: missing heading {link}")
    for image in (root / "docs" / "images").glob("*.png"):
        data = image.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            errors.append(f"Invalid PNG: {image.name}")
            continue
        offset = 8
        ended = False
        while offset + 12 <= len(data):
            size = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            offset += size + 12
            if kind in {b"tEXt", b"zTXt", b"iTXt", b"eXIf"}:
                errors.append(f"Text/EXIF metadata in screenshot: {image.name}")
            if kind == b"IEND":
                ended = True
                break
        if not ended or offset != len(data):
            errors.append(f"Truncated PNG or trailing data: {image.name}")
    return errors


if __name__ == "__main__":
    errors = check_docs()
    if errors:
        raise SystemExit("\n".join(errors))
    print("Documentation links, image targets, and PNG metadata checks passed.")
