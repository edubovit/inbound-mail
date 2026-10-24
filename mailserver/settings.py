import json
import os
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = os.environ.get("MAIL_CONFIG")
CONFIG = json.loads(Path(CONFIG_PATH).read_text()) if CONFIG_PATH else {}
DEVELOPMENT = not CONFIG_PATH
DATA_DIR = Path(CONFIG["data_dir"] if CONFIG_PATH else os.environ.get("MAIL_DEV_DATA", BASE_DIR.parent / ".local" / "data"))
MAIL_DOMAIN = CONFIG.get("domain", "mail.test").lower()
SMTP_HOSTNAME = CONFIG.get("smtp_hostname", MAIL_DOMAIN).lower()
UI_URL = CONFIG.get("ui_url", "http://127.0.0.1:8000")
UI_HOST = urlsplit(UI_URL).hostname
SECRET_KEY = CONFIG["secret_key"] if CONFIG_PATH else "local-development-only-not-for-deployment"
DEBUG = False
ALLOWED_HOSTS = [UI_HOST] + (["localhost", "testserver"] if DEVELOPMENT else [])
CSRF_TRUSTED_ORIGINS = [UI_URL]
ROOT_URLCONF = "mailserver.urls"
WSGI_APPLICATION = "mailserver.wsgi.application"
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "mailserver"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "mailserver.middleware.SecurityMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
    ]},
}]
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": DATA_DIR / "mail.sqlite3",
    "OPTIONS": {"timeout": 15, "transaction_mode": "IMMEDIATE",
                "init_command": "PRAGMA synchronous=EXTRA; PRAGMA secure_delete=ON;"},
}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "mailserver.Account"
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
AUTH_PASSWORD_VALIDATORS = []
LOGIN_URL = "/login/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_SECURE = not DEVELOPMENT
CSRF_COOKIE_SECURE = not DEVELOPMENT
SESSION_COOKIE_AGE = 12 * 60 * 60
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = not DEVELOPMENT
SECURE_HSTS_SECONDS = 31536000 if not DEVELOPMENT else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 30
USE_TZ = True
TIME_ZONE = "UTC"
MAX_MESSAGE_BYTES = int(CONFIG.get("max_message_mib", 25)) * 1024**2
DEFAULT_QUOTA_BYTES = int(CONFIG.get("mailbox_quota_mib", 1024)) * 1024**2
DISK_RESERVE_BYTES = int(CONFIG.get("disk_reserve_mib", 1024)) * 1024**2
SMTP_HOST = CONFIG.get("smtp_host", "127.0.0.1")
SMTP_PORT = int(CONFIG.get("smtp_port", 2525))
SMTP_CONNECTIONS = int(CONFIG.get("smtp_connections", 16))
SMTP_MESSAGES_PER_HOUR = int(CONFIG.get("smtp_messages_per_ip_hour", 120))
SMTP_RECIPIENTS = int(CONFIG.get("smtp_recipients", 50))
TLS_CERT = CONFIG.get("tls_cert")
TLS_KEY = CONFIG.get("tls_key")
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {"mailserver": {"level": "INFO"}, "mail.log": {"level": "CRITICAL"}},
}
