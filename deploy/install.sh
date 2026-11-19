#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/handtodigital"
APP_USER="handtodigital"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script with sudo."
  exit 1
fi

if [[ ! -f "$APP_DIR/app/main.py" ]]; then
  echo "Application source not found at $APP_DIR. Clone the repository there first."
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip nginx

id "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
install -m 0644 "$APP_DIR/deploy/handtodigital.service" /etc/systemd/system/handtodigital.service
install -m 0644 "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/handtodigital
ln -sfn /etc/nginx/sites-available/handtodigital /etc/nginx/sites-enabled/handtodigital
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl daemon-reload
systemctl enable --now handtodigital
systemctl enable --now nginx
systemctl restart nginx

echo "HandToDigital installed. Check: systemctl status handtodigital nginx"
