import argparse
import json
import os
import ssl
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def certificate_hosts(config):
    return {config.get("smtp_hostname", config["domain"]).lower(), urlsplit(config["ui_url"]).hostname}


def main():
    import grp

    parser = argparse.ArgumentParser()
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run as root")
    config = json.loads(Path("/etc/inbound-mail/config.json").read_text())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(config["certificate_source"], config["private_key_source"])
    for host in certificate_hosts(config):
        subprocess.run(["openssl", "x509", "-in", config["certificate_source"], "-noout", "-checkhost", host], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["openssl", "x509", "-in", config["certificate_source"], "-noout", "-checkend", "86400"], check=True, stdout=subprocess.DEVNULL)
    group = grp.getgrnam("inbound-mail").gr_gid
    for source, target in [("certificate_source", "tls_cert"), ("private_key_source", "tls_key")]:
        destination = Path(config[target])
        temporary = destination.with_suffix(".new")
        with temporary.open("wb") as output:
            os.chmod(temporary, 0o640)
            os.chown(temporary, 0, group)
            output.write(Path(config[source]).read_bytes())
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    if not args.no_restart:
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        subprocess.run(["systemctl", "restart", "inbound-mail-smtp"], check=True)


if __name__ == "__main__":
    main()
