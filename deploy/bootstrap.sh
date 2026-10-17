#!/usr/bin/env bash
#
# One-time server setup for the Pasons Smart QR platform.
# Run as root on a fresh Ubuntu droplet, once:
#
#     bash deploy/bootstrap.sh 139.59.84.247
#
# It installs the runtime packages, adds a 1 GB swap file (the 1 vCPU / 1 GB
# droplets need it), creates the `pasons` service user, the PostgreSQL role
# and database, and writes a production .env with a freshly generated
# SECRET_KEY and database password.
#
# It never needs a key from the repository. The AI provider keys are left
# blank on purpose: they are pasted into .env on the server, so they are
# never copied from a laptop, a commit or a chat.
#
# Safe to run twice: every step checks before it acts.

set -euo pipefail

HOST_NAME="${1:-}"

APP_USER="pasons"
APP_DIR="/srv/pasons/platform"
ENV_FILE="$APP_DIR/.env"
DB_NAME="pasons"
DB_ROLE="pasons"
DB_PASS_FILE="/root/.pasons_db_password"

log() { printf '\n==> %s\n' "$1"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this as root (sudo bash deploy/bootstrap.sh <host>)." >&2
  exit 1
fi

if [ -z "$HOST_NAME" ]; then
  HOST_NAME="$(hostname -I | awk '{print $1}')"
fi

# --- packages -------------------------------------------------------------
log "Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  python3-venv python3-pip nginx postgresql postgresql-contrib rsync curl

# --- swap ----------------------------------------------------------------
if swapon --show | grep -q .; then
  log "Swap already present, leaving it alone"
else
  log "Adding a 1 GB swap file"
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- service user ---------------------------------------------------------
if id "$APP_USER" >/dev/null 2>&1; then
  log "User $APP_USER already exists"
else
  log "Creating the $APP_USER service user"
  useradd --create-home --shell /bin/bash "$APP_USER"
fi

mkdir -p "$APP_DIR/media" "$APP_DIR/staticfiles"
chown -R "$APP_USER:$APP_USER" "$(dirname "$APP_DIR")"
# 755 so nginx can read static files and uploaded media. The .env inside
# stays 600 and owned by the service user.
chmod 755 "$APP_DIR"

# --- database -------------------------------------------------------------
if [ -f "$DB_PASS_FILE" ]; then
  DB_PASS="$(cat "$DB_PASS_FILE")"
else
  DB_PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  printf '%s' "$DB_PASS" > "$DB_PASS_FILE"
  chmod 600 "$DB_PASS_FILE"
fi

if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_ROLE'" | grep -q 1; then
  log "PostgreSQL role $DB_ROLE already exists"
else
  log "Creating the PostgreSQL role and database"
  runuser -u postgres -- psql -c "CREATE ROLE $DB_ROLE LOGIN PASSWORD '$DB_PASS';"
fi

if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  log "Database $DB_NAME already exists"
else
  runuser -u postgres -- createdb --owner="$DB_ROLE" "$DB_NAME"
fi

# Keep the role password in sync with the stored secret on a re-run.
runuser -u postgres -- psql -c "ALTER ROLE $DB_ROLE PASSWORD '$DB_PASS';" >/dev/null

# --- environment file -----------------------------------------------------
if [ -f "$ENV_FILE" ]; then
  log ".env already exists, not touching it"
else
  log "Writing $ENV_FILE with a fresh SECRET_KEY"
  SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
  install -m 600 -o "$APP_USER" -g "$APP_USER" /dev/null "$ENV_FILE"
  cat > "$ENV_FILE" <<EOF
# Pasons Smart QR - production environment.
# Owner: $APP_USER, mode 600. Never commit this file, never paste it in chat.

# --- Django ---------------------------------------------------------------
SECRET_KEY=$SECRET_KEY
DEBUG=0
ALLOWED_HOSTS=$HOST_NAME
CSRF_TRUSTED_ORIGINS=http://$HOST_NAME
SERVE_MEDIA=0
USE_X_FORWARDED_PROTO=0

# --- HTTPS ----------------------------------------------------------------
# Turn these on only after the site answers on https:// with a certificate.
# Over plain http:// they must stay 0 or every request redirects to a dead port.
SECURE_SSL_REDIRECT=0
SESSION_COOKIE_SECURE=0
CSRF_COOKIE_SECURE=0
SECURE_HSTS_SECONDS=0

# --- PostgreSQL -----------------------------------------------------------
POSTGRES_DB=$DB_NAME
POSTGRES_USER=$DB_ROLE
POSTGRES_PASSWORD=$DB_PASS
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432

# --- AI review assist -----------------------------------------------------
# Paste the provider key here on the server. Left blank, the review composer
# still works: it tidies the guest's own words and never invents sentences.
MIMO_API_KEY=
MIMO_TOKEN_PLAN_API_KEY=
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_TOKEN_PLAN_URL=https://token-plan-sgp.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2.6-flash
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# --- Guest sign-in (optional) --------------------------------------------
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
EOF
fi

chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

log "Bootstrap complete"
echo "Next: run deploy/deploy.sh from the project machine to push the code."
