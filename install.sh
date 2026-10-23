#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

main() {
APP=/opt/inbound-mail
CONF=/etc/inbound-mail
DATA=/var/lib/inbound-mail
SITE=/etc/nginx/sites-available/inbound-mail
ENABLED=/etc/nginx/sites-enabled/inbound-mail
SOURCE=
ACTION=install

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
ask() {
    local value
    read -r -p "$2${3:+ [$3]}: " value </dev/tty
    printf -v "$1" '%s' "${value:-${3:-}}"
}
confirm() {
    local answer
    ask answer "$1 Type yes to continue" no
    [[ "$answer" == yes ]]
}
port_used() { ss -H -lnt "sport = :$1" | grep -q .; }
valid_domain() {
    [[ ${#1} -le 253 && "$1" == *.* && "$1" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && "$1" != *..* ]] || return 1
    local label
    local -a labels
    IFS=. read -ra labels <<< "$1"
    for label in "${labels[@]}"; do
        [[ ${#label} -le 63 && "$label" != -* && "$label" != *- ]] || return 1
    done
}
number() { [[ "$1" =~ ^[1-9][0-9]{0,6}$ ]] && (( 10#$1 <= $2 )); }

while (($#)); do
    case "$1" in
        install|uninstall) ACTION=$1; shift ;;
        --source) [[ $# -ge 2 ]] || die '--source requires a directory'; SOURCE=$2; shift 2 ;;
        --help) printf 'Usage: sudo bash install.sh [install|uninstall] [--source trusted-checkout]\nPrompts always read from /dev/tty. No upgrades or unattended purge.\n'; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

[[ $EUID -eq 0 ]] || die 'Run as root: curl -fsSL https://raw.githubusercontent.com/edubovit/inbound-mail/master/install.sh | sudo bash'
exec </dev/tty || die 'An interactive terminal is required'
[[ -d /run/systemd/system ]] || die 'A running systemd system is required'

uninstall() {
    local destination=
    [[ -f "$CONF/owned" && ! -L "$CONF" && ! -L "$APP" && ! -L "$DATA" ]] || die 'No owned installation found, or an owned directory is a symlink'
    printf 'Uninstall permanently deletes all accounts, mail, app configuration, and owned certificates. Shared packages and services remain.\n'
    if [[ -f "$DATA/mail.sqlite3" ]] && confirm 'Export mail before uninstalling?'; then
        ask destination 'Absolute path for a new export archive (outside application directories)'
        [[ "$destination" == /* && "$destination" != "$APP"/* && "$destination" != "$CONF"/* && "$destination" != "$DATA"/* ]] || die 'Choose an absolute path outside owned directories'
        "$APP/venv/bin/python" -m mailserver.cli --config "$CONF/config.json" export "$destination"
    fi
    confirm 'Purge this installation and all its mail?' || exit 0
    systemctl disable --now inbound-mail-renew.timer inbound-mail-web.service inbound-mail-smtp.service 2>/dev/null || true
    systemctl stop inbound-mail-renew.service 2>/dev/null || true
    if [[ -e "$ENABLED" || -L "$ENABLED" ]]; then
        [[ "$(readlink "$ENABLED")" == "$SITE" ]] || die 'nginx site ownership changed; refusing removal'
        rm "$ENABLED"
        if ! nginx -t; then
            ln -s "$SITE" "$ENABLED"
            die 'nginx configuration invalid without our site; restored link, purge stopped'
        fi
        systemctl reload nginx
    fi
    rm -f "$SITE" /etc/systemd/system/inbound-mail-{web,smtp,renew}.service /etc/systemd/system/inbound-mail-renew.timer /usr/local/bin/inbound-mail
    rm -rf -- "$APP" "$DATA" "$CONF" /var/log/inbound-mail-acme
    userdel inbound-mail 2>/dev/null || true
    systemctl daemon-reload
    printf 'Uninstalled. Export files and shared packages/services were not removed. Remove the mail DNS records separately.\n'
}

if [[ "$ACTION" == uninstall ]]; then uninstall; exit; fi

. /etc/os-release
[[ "$ID" == ubuntu || "$ID" == debian ]] || die 'Only Ubuntu and Debian are supported'
if [[ "$ID" != ubuntu || "$VERSION_ID" != 26.04 ]]; then
    confirm "This is $PRETTY_NAME, not the reference Ubuntu 26.04. Continue best-effort?" || exit 0
fi
for path in "$APP" "$CONF" "$DATA" "$SITE" "$ENABLED" /usr/local/bin/inbound-mail /var/log/inbound-mail-acme /etc/systemd/system/inbound-mail-web.service /etc/systemd/system/inbound-mail-smtp.service /etc/systemd/system/inbound-mail-renew.service /etc/systemd/system/inbound-mail-renew.timer; do
    [[ ! -e "$path" && ! -L "$path" ]] || die "Path already exists: $path. Reinstallation/upgrades are not supported."
done
! id inbound-mail &>/dev/null || die 'The inbound-mail OS account already exists'
command -v python3 >/dev/null || die 'Install Python 3.12+ before running this installer'
python3 -c 'import sys; assert sys.version_info >= (3,12)' || die 'Python 3.12+ is required'
command -v ss >/dev/null || die 'Install iproute2 first'
! port_used 25 || die 'TCP 25 is already occupied; existing mail services will not be changed'
if command -v nginx >/dev/null; then nginx -t || die 'Existing nginx configuration is invalid'; fi

ask DOMAIN 'Receiving domain (ASCII, lowercase)'
valid_domain "$DOMAIN" || die 'Invalid domain'
ask UI_URL 'Public UI URL (https://hostname, no path)' "https://$DOMAIN"
[[ "$UI_URL" =~ ^https://([^/:]+)(:([0-9]+))?/?$ ]] || die 'Use an HTTPS URL without credentials, query, or path'
UI_HOST=${BASH_REMATCH[1]}
PUBLIC_PORT=${BASH_REMATCH[3]:-443}
if ! valid_domain "$UI_HOST" || ! number "$PUBLIC_PORT" 65535; then die 'Invalid UI hostname or port'; fi
UI_URL=${UI_URL%/}
ask IP 'Public IPv4 for DNS records'
python3 -c 'import ipaddress,sys; ipaddress.IPv4Address(sys.argv[1])' "$IP" || die 'Invalid IPv4 address'
ask WEB_PORT 'Loopback application port' 20025
ask NGINX_PORT 'nginx HTTPS listener port (use existing backend port for an external TLS router)' "$PUBLIC_PORT"
if ! number "$WEB_PORT" 65535 || ! number "$NGINX_PORT" 65535; then die 'Invalid port'; fi
[[ "$WEB_PORT" != "$NGINX_PORT" && "$WEB_PORT" != 25 && "$NGINX_PORT" != 25 ]] || die 'Ports must be distinct from SMTP and each other'
! port_used "$WEB_PORT" || die 'Application port is occupied'
if port_used "$NGINX_PORT"; then
    ss -H -lntp "sport = :$NGINX_PORT" | grep -q nginx || die 'HTTPS listener is owned by another service; choose an nginx backend port'
    confirm "Add a dedicated virtual host to existing nginx port $NGINX_PORT?" || exit 0
fi
if command -v nginx >/dev/null && nginx -T 2>/dev/null | grep -E '^[[:space:]]*server_name ' | grep -Fwq "$UI_HOST"; then
    die 'The UI hostname is already configured in nginx'
fi
ask MAX_MIB 'Maximum incoming message size (MiB)' 25
ask QUOTA_MIB 'Default mailbox quota (MiB)' 1024
ask RESERVE_MIB 'Free-disk reserve (MiB)' 1024
if ! number "$MAX_MIB" 100 || ! number "$QUOTA_MIB" 1048576 || ! number "$RESERVE_MIB" 1048576; then
    die 'Invalid limits (message maximum: 100 MiB)'
fi
printf '\nSet these DNS records (DNS-only, not proxied):\n%s. A %s\n%s. MX 10 %s.\n' "$DOMAIN" "$IP" "$DOMAIN" "$DOMAIN"
[[ "$UI_HOST" == "$DOMAIN" ]] || printf '%s. A %s\n' "$UI_HOST" "$IP"
printf 'Do not publish AAAA until IPv6 is configured. Allow inbound TCP 25, HTTPS, and TCP 80 for standalone certificate validation. Firewall/provider rules are not changed automatically.\n'
confirm 'DNS and inbound firewall/provider rules are ready?' || exit 0
ask CERT_MODE 'TLS: standalone (automatic ACME, TCP 80 must be free) or existing (operator-managed PEM)' standalone
[[ "$CERT_MODE" == standalone || "$CERT_MODE" == existing ]] || die 'Invalid TLS mode'
CERT_SOURCE=
KEY_SOURCE=
if [[ "$CERT_MODE" == standalone ]]; then
    ! port_used 80 || die 'TCP 80 is occupied. Use existing certificates, or arrange a compatible ACME method separately; no service will be stopped.'
    ask ACME_EMAIL 'External contact email for certificate account recovery (blank to omit)'
    [[ -z "$ACME_EMAIL" || ( "$ACME_EMAIL" == *@*.* && "$ACME_EMAIL" != -* ) ]] || die 'Invalid contact email'
    confirm "Agree to the Let's Encrypt subscriber agreement and request a public certificate for $DOMAIN and $UI_HOST?" || exit 0
else
    ask CERT_SOURCE 'Absolute path to PEM full chain (must cover receiving domain and UI hostname)'
    ask KEY_SOURCE 'Absolute path to PEM private key'
    [[ "$CERT_SOURCE" == /* && "$KEY_SOURCE" == /* && -f "$CERT_SOURCE" && -f "$KEY_SOURCE" ]] || die 'Certificate files do not exist'
fi
ask ADMIN 'First ADMIN username'
[[ "$ADMIN" =~ ^[a-z0-9]([a-z0-9._-]{0,62}[a-z0-9])?$ && "$ADMIN" != *..* ]] || die 'Invalid admin username'
printf 'The password will be prompted securely after package installation; it is never a command-line argument.\n'
confirm 'Install dependencies, create owned services and data, and add the dedicated nginx site?' || exit 0

WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
trap 'printf "Installation stopped at line %s. No automatic retry/upgrade is performed. If owned paths were created, use the installer uninstall command to remove the partial installation.\n" "$LINENO" >&2' ERR
if [[ -n "$SOURCE" ]]; then
    SOURCE=$(realpath "$SOURCE")
    [[ -f "$SOURCE/pyproject.toml" && -f "$SOURCE/install.sh" && -d "$SOURCE/mailserver" ]] || die 'Not a source checkout'
else
    command -v curl >/dev/null || die 'Install curl first'
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 --retry 3 \
        --output "$WORK/commit.json" https://api.github.com/repos/edubovit/inbound-mail/commits/master
    REVISION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha"])' "$WORK/commit.json")
    [[ "$REVISION" =~ ^[a-f0-9]{40}$ ]] || die 'GitHub returned an invalid commit ID'
    printf 'Downloading inbound-mail source at commit %s\n' "$REVISION"
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 --retry 3 \
        --output "$WORK/release.tar.gz" "https://codeload.github.com/edubovit/inbound-mail/tar.gz/$REVISION"
    python3 - "$WORK" <<'PY'
import pathlib, sys, tarfile
root = pathlib.Path(sys.argv[1])
with tarfile.open(root / 'release.tar.gz') as archive:
    archive.extractall(root / 'source', filter='data')
PY
    SOURCE="$WORK/source/inbound-mail-$REVISION"
    [[ -f "$SOURCE/pyproject.toml" && -d "$SOURCE/mailserver" ]] || die 'Invalid release structure'
fi

install -d -m 750 "$CONF"
touch "$CONF/owned"
install -d -m 755 "$APP"
cp -R "$SOURCE/mailserver" "$APP/"
cp "$SOURCE/pyproject.toml" "$SOURCE/requirements.txt" "$SOURCE/install.sh" "$APP/"
install -d -m 755 "$APP/deploy"
cp "$SOURCE/deploy/refresh_tls.py" "$APP/deploy/"
HAD_NGINX=no
command -v nginx >/dev/null && HAD_NGINX=yes
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-venv nginx certbot ca-certificates dnsutils curl
if [[ "$HAD_NGINX" == no ]]; then
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
    systemctl reload nginx
fi
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --disable-pip-version-check "$APP"
chmod -R a+rX "$APP"
useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin inbound-mail
install -d -o inbound-mail -g inbound-mail -m 700 "$DATA"
chgrp inbound-mail "$CONF"
install -d -m 750 -g inbound-mail "$CONF/tls"

if [[ "$CERT_MODE" == standalone ]]; then
    ! port_used 80 || die 'TCP 80 became occupied; cannot safely request certificate'
    [[ "$(dig +short A "$DOMAIN" | tail -n1)" == "$IP" ]] || die 'Receiving-domain A record does not match the supplied IPv4'
    [[ "$(dig +short A "$UI_HOST" | tail -n1)" == "$IP" ]] || die 'UI A record does not match the supplied IPv4'
    dig +short MX "$DOMAIN" | grep -Fxiq "10 $DOMAIN." || die 'Expected MX record is not visible yet'
    for name in "$DOMAIN" "$UI_HOST"; do
        [[ -z "$(dig +short AAAA "$name")" ]] || die 'Remove unverified AAAA records before this IPv4-only installation'
    done
    CONTACT=(--register-unsafely-without-email)
    [[ -z "$ACME_EMAIL" ]] || CONTACT=(--email "$ACME_EMAIL")
    certbot certonly --standalone --non-interactive --agree-tos "${CONTACT[@]}" --cert-name inbound-mail \
        --config-dir "$CONF/acme" --work-dir "$CONF/acme-work" --logs-dir /var/log/inbound-mail-acme \
        -d "$DOMAIN" -d "$UI_HOST"
    CERT_SOURCE="$CONF/acme/live/inbound-mail/fullchain.pem"
    KEY_SOURCE="$CONF/acme/live/inbound-mail/privkey.pem"
fi

python3 - "$CONF/config.json" "$DOMAIN" "$UI_URL" "$MAX_MIB" "$QUOTA_MIB" "$RESERVE_MIB" "$CERT_SOURCE" "$KEY_SOURCE" <<'PY'
import json, secrets, sys
path, domain, url, maximum, quota, reserve, cert, key = sys.argv[1:]
config = dict(domain=domain, ui_url=url, secret_key=secrets.token_urlsafe(48), data_dir='/var/lib/inbound-mail',
              max_message_mib=int(maximum), mailbox_quota_mib=int(quota), disk_reserve_mib=int(reserve),
              smtp_host='0.0.0.0', smtp_port=25, tls_cert='/etc/inbound-mail/tls/fullchain.pem',
              tls_key='/etc/inbound-mail/tls/privkey.pem', certificate_source=cert, private_key_source=key)
with open(path, 'x') as output:
    json.dump(config, output, indent=2)
PY
chown root:inbound-mail "$CONF/config.json"
chmod 640 "$CONF/config.json"
python3 "$APP/deploy/refresh_tls.py" --no-restart
"$APP/venv/bin/python" -m mailserver.cli --config "$CONF/config.json" init "$ADMIN" </dev/tty
chown -R inbound-mail:inbound-mail "$DATA"
runuser -u inbound-mail -- "$APP/venv/bin/python" -m mailserver.cli --config "$CONF/config.json" check

cat > /usr/local/bin/inbound-mail <<'SH'
#!/bin/sh
exec /opt/inbound-mail/venv/bin/python -m mailserver.cli --config /etc/inbound-mail/config.json "$@"
SH
chmod 755 /usr/local/bin/inbound-mail

for service in web smtp; do
    if [[ "$service" == web ]]; then
        EXEC="$APP/venv/bin/gunicorn --bind 127.0.0.1:$WEB_PORT --workers 1 --threads 2 --worker-connections 32 --timeout 120 --no-control-socket --forwarder-headers '' mailserver.wsgi:application"
        CAPS=
    else
        EXEC="$APP/venv/bin/python -m mailserver.cli smtp"
        CAPS=CAP_NET_BIND_SERVICE
    fi
    cat > "/etc/systemd/system/inbound-mail-$service.service" <<UNIT
[Unit]
Description=Inbound mail $service
After=network.target
[Service]
User=inbound-mail
Group=inbound-mail
WorkingDirectory=$APP
Environment=MAIL_CONFIG=$CONF/config.json
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=$EXEC
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA
AmbientCapabilities=$CAPS
CapabilityBoundingSet=$CAPS
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
TasksMax=64
MemoryMax=384M
[Install]
WantedBy=multi-user.target
UNIT
done

cat > "$SITE" <<NGINX
server {
    listen $NGINX_PORT ssl;
    listen [::]:$NGINX_PORT ssl;
    server_name $UI_HOST;
    ssl_certificate $CONF/tls/fullchain.pem;
    ssl_certificate_key $CONF/tls/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 64k;
    access_log off;
    location / {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Protocol "";
        proxy_set_header X-Forwarded-Ssl "";
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For "";
        proxy_set_header SCRIPT_NAME "";
        proxy_set_header PATH_INFO "";
        proxy_buffering off;
        proxy_read_timeout 120s;
    }
}
NGINX
ln -s "$SITE" "$ENABLED"
if ! nginx -t; then rm "$ENABLED"; die 'nginx rejected the new site; existing running configuration was not reloaded'; fi

if [[ "$CERT_MODE" == standalone ]]; then
    cat > /etc/systemd/system/inbound-mail-renew.service <<UNIT
[Unit]
Description=Renew owned inbound mail certificate
[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet --config-dir $CONF/acme --work-dir $CONF/acme-work --logs-dir /var/log/inbound-mail-acme --deploy-hook "/usr/bin/python3 $APP/deploy/refresh_tls.py"
UNIT
    cat > /etc/systemd/system/inbound-mail-renew.timer <<'UNIT'
[Unit]
Description=Check inbound mail certificate twice daily
[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
UNIT
fi
systemctl daemon-reload
systemctl enable --now inbound-mail-web inbound-mail-smtp
[[ "$CERT_MODE" != standalone ]] || systemctl enable --now inbound-mail-renew.timer
systemctl reload nginx
inbound-mail check
curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 1 --max-time 5 \
    --resolve "$UI_HOST:$NGINX_PORT:127.0.0.1" "https://$UI_HOST:$NGINX_PORT/health/"
systemctl is-active --quiet inbound-mail-web inbound-mail-smtp || die 'Application services are not active'
python3 - <<'PY'
import smtplib
with smtplib.SMTP('127.0.0.1', 25, timeout=10) as client:
    assert client.ehlo()[0] == 250
PY
printf '\nInstalled: %s\nReceiving: %s\nConfig: %s/config.json\n' "$UI_URL" "$DOMAIN" "$CONF"
printf 'Verify delivery from outside this VPS. Existing Xray/proxy routing and firewalls were not changed.\n'
if [[ "$PUBLIC_PORT" != "$NGINX_PORT" ]]; then printf 'Public HTTPS must already route to nginx port %s; verify externally before using accounts.\n' "$NGINX_PORT"; fi
if [[ "$CERT_MODE" == existing ]]; then printf 'After certificate renewal, run: python3 /opt/inbound-mail/deploy/refresh_tls.py\n'; fi
printf 'Uninstall: sudo bash /opt/inbound-mail/install.sh uninstall\n'
}

main "$@"
