#!/usr/bin/env bash
#
# Push the project to the DigitalOcean droplet and restart it.
# Run from the project machine (this laptop), not on the server:
#
#     bash deploy/deploy.sh
#     HOST=139.59.84.247 bash deploy/deploy.sh
#
# The first run also installs the Python packages, runs migrations,
# collects static files, installs the nginx site and the systemd unit.
# Later runs repeat all of it, so the same command is the normal update.
#
# What is never sent: .env (the server owns its own secrets), .git,
# venv, the local SQLite database, Docs, recordings and logs.

set -euo pipefail

HOST="${HOST:-139.59.84.247}"
REMOTE_USER="${REMOTE_USER:-root}"
# The public name the site is served under, printed at the end. HOST above is
# still the droplet address, because the deploy connects to it directly.
SITE_URL="${SITE_URL:-https://qr-system.pasons.group}"
# The host part of SITE_URL, used to find the certificate certbot issued and
# to decide whether the repo's nginx file may replace the live one.
SITE_HOST="${SITE_URL#*://}"
SITE_HOST="${SITE_HOST%%/*}"
APP_USER="pasons"
APP_DIR="/srv/pasons/platform"
SERVICE="pasons"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Refuse to push a tree whose tracked media is missing. A local cleanup or a
# careless test run can move media/ aside, and rsync would then replace the
# live images with nothing. Restoring first is one git command.
if git -C "$HERE" status --porcelain -- media/ | grep -q '^ D'; then
  echo "Tracked files under media/ are missing on this machine." >&2
  echo "Restore them first:  git -C \"$HERE\" checkout -- media/" >&2
  git -C "$HERE" status --porcelain -- media/ | grep '^ D' | head -5 >&2
  exit 1
fi

printf '\n==> Pushing code to %s@%s:%s\n' "$REMOTE_USER" "$HOST" "$APP_DIR"
rsync -az --chown="$APP_USER:$APP_USER" \
  --exclude '.git/' \
  --exclude 'venv/' \
  --exclude '.env' \
  --exclude '.env.*' \
  --exclude '.cortex/' \
  --exclude '.trash/' \
  --exclude '.playwright-mcp/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'staticfiles/' \
  --exclude 'db.sqlite3' \
  --exclude '*.mp4' \
  --exclude '*.log' \
  --exclude 'Docs/' \
  --exclude 'paired-output.txt' \
  "$HERE/" "$REMOTE_USER@$HOST:$APP_DIR/"

printf '\n==> Installing, migrating, collecting, restarting\n'
# The heredoc is quoted so the remote shell owns every $ inside it. The four
# values it needs from this machine are passed on the ssh command line.
ssh "$REMOTE_USER@$HOST" \
  "APP_USER='$APP_USER' APP_DIR='$APP_DIR' SERVICE='$SERVICE' SITE_HOST='$SITE_HOST' bash -s" <<'REMOTE'
set -euo pipefail
cd "$APP_DIR"

if [ ! -x venv/bin/pip ]; then
  echo "Creating the virtualenv"
  runuser -u "$APP_USER" -- python3 -m venv venv
fi

runuser -u "$APP_USER" -- venv/bin/pip install --upgrade pip >/dev/null
runuser -u "$APP_USER" -- venv/bin/pip install -r requirements-prod.txt

# The database is PostgreSQL on the server; .env decides that by setting
# POSTGRES_DB. Without it the app would silently fall back to SQLite.
grep -q '^POSTGRES_DB=.' .env || { echo "POSTGRES_DB missing from .env"; exit 1; }
grep -q '^DEBUG=0' .env || { echo "DEBUG must be 0 in .env"; exit 1; }

runuser -u "$APP_USER" -- venv/bin/python manage.py migrate --noinput

# A production start must pass Django's own deployment checks. These five are
# expected on the current host and are not regressions:
#   W004 W008 W012 W016  the site is served over plain http://<ip> for now,
#                        so HTTPS-only settings would redirect to a dead port.
#                        They clear themselves once a certificate is installed
#                        and the four HTTPS keys in .env are set to 1.
#   W019                 X_FRAME_OPTIONS stays SAMEORIGIN on purpose: the
#                        games run in same-origin iframes.
# Anything else, and in particular W009 (weak SECRET_KEY) or W018 (DEBUG on),
# is a real problem and stops the deploy.
CHECK_OUT="$(runuser -u "$APP_USER" -- venv/bin/python manage.py check --deploy 2>&1 || true)"
printf '%s\n' "$CHECK_OUT"
ALLOWED="W004 W008 W012 W016 W019"
BAD=""
for code in $(printf '%s\n' "$CHECK_OUT" | grep -oE 'security\.W[0-9]+' | sort -u); do
  short="${code#security.}"
  case " $ALLOWED " in
    *" $short "*) ;;
    *) BAD="$BAD $code" ;;
  esac
done
if [ -n "$BAD" ]; then
  echo "Deployment check reported unexpected problems:$BAD" >&2
  exit 1
fi

runuser -u "$APP_USER" -- venv/bin/python manage.py collectstatic --noinput >/dev/null

# A production start renders {% static %} through the manifest. If the
# manifest is missing (collectstatic aborted on a broken reference), every
# page returns 500, so refuse to restart on a half-collected tree.
test -f staticfiles/staticfiles.json || {
  echo "collectstatic did not produce staticfiles.json; run it by hand" >&2
  exit 1
}

# Once HTTPS exists, certbot owns the live site file: it writes the 443 block
# and the certificate paths into it. Copying the repo's HTTP-only file over
# that would drop TLS and take the site offline over https, so the repo file is
# installed only while no certificate has been issued. FORCE_NGINX=1 restores
# it deliberately, after which https must be set up again with certbot.
CERT_FILE="/etc/letsencrypt/live/$SITE_HOST/fullchain.pem"
if [ -f "$CERT_FILE" ] && [ "${FORCE_NGINX:-0}" != "1" ]; then
  echo "Keeping the certbot managed nginx site (found $CERT_FILE)"
else
  install -m 644 deploy/nginx-pasons.conf /etc/nginx/sites-available/pasons
fi
ln -sf /etc/nginx/sites-available/pasons /etc/nginx/sites-enabled/pasons
rm -f /etc/nginx/sites-enabled/default
install -m 644 deploy/pasons.service /etc/systemd/system/pasons.service

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"
nginx -t
systemctl reload nginx

sleep 2
systemctl is-active --quiet "$SERVICE" || { journalctl -u "$SERVICE" -n 40 --no-pager; exit 1; }
REMOTE

printf '\n==> Smoke test\n'
for path in "/" "/panel/login/" "/static/css/app.css"; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST$path")"
  printf '  %-24s %s\n' "$path" "$code"
  case "$code" in
    200|301|302) ;;
    *) echo "Unexpected status for $path" >&2; exit 1 ;;
  esac
done

# Reported, never fatal: a fresh droplet has no certificate yet, and that is
# not a failed deploy. Once certbot has run, this line confirms the public
# address answers with a valid certificate.
public_code="$(curl -s -o /dev/null -w '%{http_code}' "$SITE_URL/" 2>/dev/null || echo "unreachable")"
printf '  %-24s %s\n' "public https" "$public_code"

printf '\nDeployed: http://%s/  (public: %s)\n' "$HOST" "$SITE_URL"
