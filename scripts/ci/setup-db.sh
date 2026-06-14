#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# setup-db.sh — Create the 4 required databases for PostgreSQL or MySQL
#
# Env vars consumed:
#   DB_BACKEND  — postgresql | mysql | sqlite-custom | default
#
# Databases created:
#   scrapydweb_apscheduler, scrapydweb_timertasks,
#   scrapydweb_metadata, scrapydweb_jobs
#
# Note: SQLite needs no external setup; this script is a no-op for it.
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

DBS=("scrapydweb_apscheduler" "scrapydweb_timertasks" "scrapydweb_metadata" "scrapydweb_jobs")

wait_for_service() {
  local host="$1" port="$2" max_attempts="${3:-30}" attempt=0
  echo "Waiting for ${host}:${port} to be ready..."
  until nc -z "$host" "$port" 2>/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$max_attempts" ]; then
      echo "::error::Service at ${host}:${port} not ready after ${max_attempts}s"
      exit 1
    fi
    sleep 1
  done
  echo "Service at ${host}:${port} is ready (took ${attempt}s)"
}

case "${DB_BACKEND:-default}" in
  postgresql)
    echo "=========================================="
    echo "  Setting up PostgreSQL databases"
    echo "=========================================="
    wait_for_service localhost 5432
    sudo apt-get update -qq && sudo apt-get install -y -qq postgresql-client
    for db in "${DBS[@]}"; do
      PGPASSWORD=passw0rd psql -h localhost -U circleci -d circleci \
        -c "CREATE DATABASE \"${db}\" ENCODING 'UTF8';" 2>/dev/null \
        && echo "Created PostgreSQL database: ${db}" \
        || echo "PostgreSQL database already exists: ${db}"
    done
    ;;
  mysql)
    echo "=========================================="
    echo "  Setting up MySQL databases"
    echo "=========================================="
    wait_for_service 127.0.0.1 3306
    sudo apt-get update -qq && sudo apt-get install -y -qq default-mysql-client
    for db in "${DBS[@]}"; do
      mysql -h 127.0.0.1 -u root -prootpw \
        -e "CREATE DATABASE IF NOT EXISTS \`${db}\` CHARACTER SET utf8 COLLATE utf8_general_ci;" 2>/dev/null
      echo "Created/found MySQL database: ${db}"
    done
    ;;
  sqlite-custom|default|"")
    echo "::notice::setup-db.sh: nothing to do for DB_BACKEND=${DB_BACKEND:-default}"
    ;;
  *)
    echo "::error::Unknown DB_BACKEND: '${DB_BACKEND}'"
    exit 1
    ;;
esac
