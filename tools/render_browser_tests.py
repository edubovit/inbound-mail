import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

parser = argparse.ArgumentParser(description="Render Playwright MCP snippets using disposable test credentials")
parser.add_argument("credentials", type=Path)
parser.add_argument("--base-url", required=True, help="URL of a disposable test installation")
parser.add_argument("--mail-domain", required=True, help="Receiving domain of that installation")
parser.add_argument("--artifacts-dir", default=".local", help="Output directory relative to the Playwright workspace")
args = parser.parse_args()
url = urlsplit(args.base_url)
if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
    parser.error("--base-url must be an HTTP(S) origin without credentials, path, query or fragment")
root = Path(__file__).resolve().parents[1]
credentials = json.loads(args.credentials.read_text())
config = {"base_url": args.base_url.rstrip("/"), "mail_domain": args.mail_domain, "artifacts_dir": args.artifacts_dir.rstrip("/\\")}
output = root / ".local"
output.mkdir(exist_ok=True)
for source in (root / "tests").glob("browser-*.js"):
    text = source.read_text().replace("__TEST_CREDENTIALS__", json.dumps(credentials))
    text = text.replace("__TEST_CONFIG__", json.dumps(config))
    (output / source.name).write_text(text)
