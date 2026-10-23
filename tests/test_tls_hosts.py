from deploy.refresh_tls import certificate_hosts


def test_certificates_cover_smtp_and_ui_not_receiving_domain():
    assert certificate_hosts({
        "domain": "example.com",
        "smtp_hostname": "mail.example.com",
        "ui_url": "https://web.example.com:20002",
    }) == {"mail.example.com", "web.example.com"}


def test_one_certificate_name_when_smtp_and_ui_match():
    assert certificate_hosts({
        "domain": "example.com",
        "smtp_hostname": "mail.example.com",
        "ui_url": "https://mail.example.com",
    }) == {"mail.example.com"}


def test_omitted_smtp_hostname_uses_receiving_domain():
    assert certificate_hosts({
        "domain": "example.com",
        "ui_url": "https://web.example.com",
    }) == {"example.com", "web.example.com"}
