import argparse
import hashlib
import json
import smtplib
import ssl
from email.message import EmailMessage
from email.policy import SMTP


def main():
    parser = argparse.ArgumentParser(description="Deliver test messages only to explicitly supplied recipients")
    parser.add_argument("host")
    parser.add_argument("recipients", nargs="+")
    parser.add_argument("--port", type=int, default=25)
    parser.add_argument("--large", action="store_true")
    args = parser.parse_args()
    with smtplib.SMTP(args.host, args.port, timeout=60) as client:
        assert client.ehlo()[0] == 250
        assert "starttls" in client.esmtp_features
        assert "auth" not in client.esmtp_features
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
        assert "auth" not in client.esmtp_features
        assert client.docmd("AUTH", "PLAIN invalid")[0] == 502
        assert client.mail("verification@example.org")[0] == 250
        assert client.rcpt("relay-check@example.invalid")[0] == 550
        assert client.rcpt("missing-account@" + args.recipients[0].split("@", 1)[1])[0] == 550
        client.rset()
        for subject in ["Browser MIME test", "Browser retained message"]:
            message = EmailMessage()
            message["From"] = "Verification <verification@example.org>"
            message["To"] = ", ".join(args.recipients)
            message["Subject"] = subject
            message.set_content("Browser plain text body. <script>This is text, not executable.</script>")
            message.add_alternative('<h1>Browser safe HTML</h1><p>Readable HTML.</p><script>parent.hacked=1</script><img src="https://tracker.invalid/pixel"><a href="https://tracker.invalid">External link</a><svg onload="parent.hacked=1"></svg><form action="https://tracker.invalid"><input name="x"></form>', subtype="html")
            message.add_attachment(b"Browser attachment contents.\n", maintype="text", subtype="plain", filename="../../report.txt")
            raw = message.as_bytes(policy=SMTP)
            assert client.sendmail("verification@example.org", args.recipients, raw) == {}
            print(json.dumps({"subject": subject, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "recipients": args.recipients}))
        if args.large:
            maximum = 25 * 1024**2
            assert client.mail("verification@example.org", options=[f"SIZE={maximum + 1}"])[0] == 552
            prefix = b"From: verification@example.org\r\nSubject: Maximum size test\r\n\r\n"
            count, remainder = divmod(maximum - len(prefix), 78)
            raw = prefix + (b"x" * 76 + b"\r\n") * count
            raw += b"x" * (remainder - 2) + b"\r\n" if remainder >= 2 else b"x" * remainder
            assert len(raw) == maximum
            assert client.sendmail("verification@example.org", args.recipients[:1], raw) == {}
            print(json.dumps({"maximum_size_accepted": len(raw), "oversize_rejected": True}))
    print("STARTTLS, TLS hostname/chain, relay rejection, unknown recipient, and delivery passed.")


if __name__ == "__main__":
    main()
