import argparse
import os
import smtplib
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Seed an isolated localhost UI preview; never uses production configuration")
    parser.add_argument("--deliver", action="store_true", help="Send the live-refresh fixture to the local SMTP listener")
    args = parser.parse_args()
    if args.deliver:
        message = EmailMessage()
        message["From"] = "Delivery test <delivery@example.org>"
        message["To"] = "previewadmin@mail.test"
        message["Subject"] = "Live delivery - automatic inbox refresh"
        message.set_content("This arrived over SMTP while the Inbox was already open.")
        with smtplib.SMTP("127.0.0.1", 2525, timeout=10) as client:
            client.sendmail("delivery@example.org", ["previewadmin@mail.test"], message.as_bytes(policy=SMTP))
        print("Delivered the live-refresh fixture to localhost.")
        return

    root = Path(__file__).resolve().parents[1]
    os.environ["MAIL_DEV_DATA"] = str(root / ".local" / "ui-preview")
    os.environ["DJANGO_SETTINGS_MODULE"] = "mailserver.settings"
    os.environ.pop("MAIL_CONFIG", None)
    import django

    django.setup()
    from mailserver.cli import initialize
    from mailserver.models import Account, Message
    from mailserver.storage import deliver

    initialize("previewadmin", "Local-preview-only-248!")
    Account.objects.create_user("reader", "Local-reader-only-248!")
    for sender, subject, text in [
        ("Build reports <builds@example.org>", "Release 0.2 is ready for review", "The latest build passed all checks.\n\nA small release: a darker interface and a quieter inbox."),
        ("Mara Chen <mara@example.org>", "Notes from the infrastructure review", "The review notes are attached below.\n\nNo urgent changes are required."),
        ("Workspace <notifications@example.org>", "Your weekly workspace summary", "A short summary of activity in your workspace."),
        ("Operations <ops@example.org>", "Scheduled maintenance completed", "The scheduled maintenance is complete. All services are available."),
        ("Security <security@example.org>", "Sign-in confirmation", "A new sign-in was recorded. If this was you, no action is needed."),
    ]:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = "previewadmin@mail.test"
        message["Subject"] = subject
        message.set_content(text)
        if subject == "Notes from the infrastructure review":
            message.add_alternative('<h1>Infrastructure review</h1><p>All checks passed.</p><blockquote>Keep the system small and predictable.</blockquote><script>parent.hacked=1</script><img src="https://tracker.invalid/pixel">', subtype="html")
            message.add_attachment(b"Review complete.\n", maintype="text", subtype="plain", filename="review.txt")
        deliver(["previewadmin@mail.test"], message.as_bytes(policy=SMTP))
    Message.objects.filter(subject__in=["Your weekly workspace summary", "Scheduled maintenance completed"]).update(is_read=True)
    print("Isolated local preview initialized; production mail was not accessed.")


if __name__ == "__main__":
    main()
