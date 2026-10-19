#!/usr/bin/env bash
#
# Update the live server from GitHub, using git pull.
# Runs ON the server, as root:
#
#     ssh root@139.59.84.247 'bash /srv/pasons/platform/deploy/update.sh'
#     ssh root@139.59.84.247 'bash /srv/pasons/platform/deploy/update.sh --force'
#
# The server pulls with its own read-only deploy key, so the private key
# stays on the droplet and the project machine is not needed at all.
#
# What it does, in order:
#   1. git pull --ff-only        (refuses to guess on a dirty or diverged tree)
#   2. pip install -r requirements-prod.txt
#   3. migrate
#   4. Django's own deployment check, with the known warnings allow-listed
#   5. collectstatic, and it refuses to continue without the manifest
#   6. restart gunicorn and reload nginx, then prove the service is alive
#
# It restarts nothing when the pull brought no new commit, unless --force is
# given. deploy/deploy.sh does the same build half after pushing files with
# rsync; use that one for the first install or for uncommitted work.

set -euo pipefail

APP_USER="${APP_USER:-pasons}"
APP_DIR="${APP_DIR:-/srv/pasons/platform}"
SERVICE="${SERVICE:-pasons}"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

cd "$APP_DIR"

as_app() { runuser -u "$APP_USER" -- "$@"; }

if [ ! -d .git ]; then
  echo "$APP_DIR is not a git checkout. Use deploy/deploy.sh for the first install." >&2
  exit 1
fi

BEFORE="$(as_app git rev-parse HEAD)"
echo "==> git pull --ff-only (currently ${BEFORE:0:7})"
as_app git pull --ff-only
AFTER="$(as_app git rev-parse HEAD)"

if [ "$BEFORE" = "$AFTER" ] && [ "$FORCE" -eq 0 ]; then
  echo "Already at ${AFTER:0:7}, nothing to rebuild. Use --force to rebuild anyway."
  exit 0
fi

echo "==> Building ${BEFORE:0:7} -> ${AFTER:0:7}"
as_app venv/bin/pip install --upgrade pip >/dev/null
as_app venv/bin/pip install -r requirements-prod.txt

grep -q '^POSTGRES_DB=.' .env || { echo "POSTGRES_DB missing from .env" >&2; exit 1; }
grep -q '^DEBUG=0' .env || { echo "DEBUG must be 0 in .env" >&2; exit 1; }

as_app venv/bin/python manage.py migrate --noinput

# Same allow-list as deploy.sh. W004 W008 W012 W016 are expected over plain
# http, W019 is deliberate because the games run in same-origin iframes.
# Anything else, especially W009 or W018, is a real problem and stops here.
CHECK_OUT="$(as_app venv/bin/python manage.py check --deploy 2>&1 || true)"
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

as_app venv/bin/python manage.py collectstatic --noinput >/dev/null
test -f staticfiles/staticfiles.json || {
  echo "collectstatic did not produce staticfiles.json; not restarting" >&2
  exit 1
}

systemctl restart "$SERVICE"
nginx -t >/dev/null
systemctl reload nginx
sleep 2
systemctl is-active --quiet "$SERVICE" || {
  journalctl -u "$SERVICE" -n 40 --no-pager
  exit 1
}

echo "Updated to ${AFTER:0:7} and restarted $SERVICE"
