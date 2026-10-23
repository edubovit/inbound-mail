import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

CONF = Path("/etc/inbound-mail")
STATE = CONF / "nginx-shared.json"
SNIPPET = CONF / "nginx-root.conf"
RESERVED = {"login", "logout", "password", "messages", "admin", "assets", "inbox", "health", "favicon.ico"}


def directives(text):
    tokens = [(m.group(), m.start(), m.end()) for m in re.finditer(
        r'''\s+|\#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{};]|[^\s{};\#"']+''', text
    ) if not m.group().isspace() and not m.group().startswith("#")]
    index = 0

    def parse(nested=False):
        nonlocal index
        result = []
        while index < len(tokens):
            if tokens[index][0] == "}":
                if not nested:
                    raise ValueError("Unbalanced nginx configuration")
                index += 1
                return result
            start = tokens[index][1]
            words = []
            while index < len(tokens) and tokens[index][0] not in {"{", "}", ";"}:
                words.append(tokens[index][0].strip("\"'"))
                index += 1
            if not words or index == len(tokens) or tokens[index][0] == "}":
                raise ValueError("Unsupported nginx syntax; configure integration manually")
            block = tokens[index][0] == "{"
            index += 1
            children = parse(True) if block else []
            result.append((words, start, tokens[index - 1][2], children))
        if nested:
            raise ValueError("Unbalanced nginx configuration")
        return result

    return parse()


def insertion(text, hostname, port, snippet):
    matches = []
    for words, start, end, children in directives(text):
        if words != ["server"]:
            continue
        names = [name for item, *_ in children if item[0] == "server_name" for name in item[1:]]
        listens = [item for item, *_ in children if item[0] == "listen"]
        if hostname not in names or not any(item[1].split(":")[-1] == str(port) for item in listens):
            continue
        if names != [hostname] or any(item[1].split(":")[-1] != str(port) or "ssl" not in item for item in listens):
            raise ValueError("Shared block must have exactly the UI hostname and only the selected TLS port")
        for item, *_ in children:
            if item[0] in {"include", "return", "rewrite", "if", "try_files", "error_page"}:
                raise ValueError("Shared block contains server-level routing/includes; integrate manually")
            if item[0] == "location":
                path = item[-1]
                if "~" in item or "~*" in item or path == "/" or path.startswith("@") or any(path.startswith("/" + name) or ("/" + name).startswith(path) for name in RESERVED):
                    raise ValueError("Existing location overlaps mail routes or uses regex/named routing")
        matches.append(end - 1)
    if len(matches) != 1:
        raise ValueError("Select a file containing exactly one matching explicit TLS server block")
    marker = f'\n    # BEGIN inbound-mail managed root\n    include "{snippet}";\n    # END inbound-mail managed root\n'
    if "inbound-mail managed root" in text or str(snippet) in text:
        raise ValueError("Mail integration already exists; refusing duplicate insertion")
    at = matches[0]
    return text[:at] + marker + text[at:], marker


def root_location(port):
    if not 1 <= port <= 65535:
        raise ValueError("Invalid application port")
    return f'''location / {{
    proxy_pass http://127.0.0.1:{port};
    client_max_body_size 64k;
    access_log off;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Protocol "";
    proxy_set_header X-Forwarded-Ssl "";
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For "";
    proxy_set_header SCRIPT_NAME "";
    proxy_set_header PATH_INFO "";
    proxy_buffering off;
    proxy_read_timeout 120s;
}}
'''


def validate():
    result = subprocess.run(["nginx", "-t"], capture_output=True, text=True, check=False)
    if result.returncode or "conflicting server name" in result.stderr + result.stdout:
        raise ValueError("nginx rejected shared-site configuration:\n" + result.stderr + result.stdout)


def replace(path, text):
    original = path.stat()
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, stat.S_IMODE(original.st_mode))
        if hasattr(os, "chown"):
            os.chown(name, original.st_uid, original.st_gid)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def attach(site, hostname, port, web_port):
    site = site.resolve(strict=True)
    if STATE.exists() or SNIPPET.exists():
        raise ValueError("Shared integration already recorded; refusing overwrite")
    original = site.read_bytes().decode("utf-8")
    updated, marker = insertion(original, hostname, port, SNIPPET)
    validate()
    STATE.write_text(json.dumps({"site": str(site), "marker": marker}, indent=2))
    STATE.chmod(0o600)
    SNIPPET.write_text(root_location(web_port))
    SNIPPET.chmod(0o644)
    changed = False
    try:
        if site.read_bytes().decode("utf-8") != original:
            raise ValueError("Shared site changed during installation")
        replace(site, updated)
        changed = True
        validate()
    except Exception:
        if changed:
            replace(site, original)
        STATE.unlink()
        SNIPPET.unlink()
        raise


def detach():
    state = json.loads(STATE.read_text())
    site = Path(state["site"])
    if site.is_symlink():
        raise ValueError("Shared site ownership changed: path is now a symlink")
    original = site.read_bytes().decode("utf-8")
    marker = state["marker"]
    if original.count(marker) != 1:
        raise ValueError("Managed include was edited or removed; refusing unsafe cleanup")
    updated = original.replace(marker, "", 1)
    if str(SNIPPET) in updated:
        raise ValueError("Another reference to the owned snippet remains; cleanup required")
    replace(site, updated)
    try:
        validate()
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
    except Exception:
        replace(site, original)
        raise
    SNIPPET.unlink()
    STATE.unlink()


def main():
    parser = argparse.ArgumentParser(description="Attach or remove an owned root location in an existing nginx site")
    parser.add_argument("action", choices=["check", "attach", "detach"])
    parser.add_argument("--site", type=Path)
    parser.add_argument("--hostname")
    parser.add_argument("--port", type=int)
    parser.add_argument("--web-port", type=int, default=20025)
    args = parser.parse_args()
    if args.action != "check" and os.geteuid() != 0:
        parser.error("Run as root")
    try:
        if args.action == "detach":
            detach()
        else:
            if not args.site or not args.site.is_absolute() or not args.hostname or not args.port:
                parser.error("--site (absolute), --hostname and --port are required")
            if args.action == "check":
                insertion(args.site.read_text(), args.hostname, args.port, SNIPPET)
            else:
                attach(args.site, args.hostname, args.port, args.web_port)
        print(f"Shared nginx {args.action}: complete")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
