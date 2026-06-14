#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# setup-env.sh — Set DATABASE_URL and DATA_PATH based on DB_BACKEND
#
# Env vars consumed:
#   DB_BACKEND  — default | postgresql | mysql | sqlite-custom
#
# Env vars written to $GITHUB_ENV (for GitHub Actions):
#   DATABASE_URL, DATA_PATH, SCRAPYDWEB_TESTMODE
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

# When running outside GitHub Actions, GITHUB_ENV may not exist.
# Create a temp file so '>> $GITHUB_ENV' still works harmlessly.
: "${GITHUB_ENV:=/dev/null}"
: "${GITHUB_WORKSPACE:=$(pwd)}"

case "${DB_BACKEND:-default}" in
  postgresql)
    DATABASE_URL="postgresql://circleci:passw0rd@localhost:5432"
    echo "DATABASE_URL=${DATABASE_URL}" >> "$GITHUB_ENV"
    echo "::notice::Using PostgreSQL backend: ${DATABASE_URL}"
    ;;
  mysql)
    DATABASE_URL="mysql://root:rootpw@127.0.0.1:3306"
    echo "DATABASE_URL=${DATABASE_URL}" >> "$GITHUB_ENV"
    echo "::notice::Using MySQL backend: ${DATABASE_URL}"
    ;;
  sqlite-custom)
    CUSTOM_DATA_PATH="${GITHUB_WORKSPACE}/scrapydweb_data"
    CUSTOM_DB_PATH="${GITHUB_WORKSPACE}/scrapydweb_database"
    mkdir -p "$CUSTOM_DATA_PATH" "$CUSTOM_DB_PATH"
    echo "DATA_PATH=${CUSTOM_DATA_PATH}" >> "$GITHUB_ENV"
    echo "DATABASE_URL=sqlite:///${CUSTOM_DB_PATH}" >> "$GITHUB_ENV"
    export DATA_PATH="$CUSTOM_DATA_PATH"
    export DATABASE_URL="sqlite:///${CUSTOM_DB_PATH}"
    echo "::notice::Using custom SQLite — DATA_PATH=${CUSTOM_DATA_PATH}, DATABASE_URL=${DATABASE_URL}"
    ;;
  default|"")
    echo "::notice::Using default SQLite backend (no DATABASE_URL override)"
    ;;
  *)
    echo "::error::Unknown DB_BACKEND: '${DB_BACKEND}'. Expected: default|postgresql|mysql|sqlite-custom"
    exit 1
    ;;
esac

echo "SCRAPYDWEB_TESTMODE=True" >> "$GITHUB_ENV"
export SCRAPYDWEB_TESTMODE=True

echo "setup-env.sh completed successfully"
