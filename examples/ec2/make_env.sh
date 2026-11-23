#!/usr/bin/env bash
# Writes .env next to this script with three fresh secrets, for docker-compose.yml.
# Refuses to overwrite: Postgres keeps the password it was first started with.
set -euo pipefail
cd "$(dirname "$0")"
if [ -e .env ]; then
  echo ".env already exists. To start over: docker compose down -v (deletes every key), rm .env, run again." >&2
  exit 1
fi
umask 077
cat > .env <<ENV
LITELLM_MASTER_KEY=sk-$(openssl rand -hex 32)
LITELLM_SALT_KEY=sk-$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -hex 32)
ENV
echo "wrote $PWD/.env"
