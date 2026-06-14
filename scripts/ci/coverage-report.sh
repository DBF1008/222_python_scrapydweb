#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# coverage-report.sh — Generate coverage reports and optionally upload
#
# Env vars consumed:
#   UPLOAD_COVERAGE  — true | false (default: false)
#   DB_BACKEND       — used for coverage flag naming
#   PYTHON_VERSION   — used for coverage flag naming
#
# Always generates: coverage report, htmlcov/, coverage.xml
# Uploads to Codecov + Coveralls only when UPLOAD_COVERAGE=true
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

echo "DATA_PATH: ${DATA_PATH:-<not set>}"
echo "DATABASE_URL: ${DATABASE_URL:-<not set>}"

echo ""
echo "=========================================="
echo "  Generating coverage reports"
echo "=========================================="
coverage report || true
coverage html || true
coverage xml || true

echo ""
ls -la allure-results 2>/dev/null || echo "No allure-results directory (Allure not enabled)"

if [ "${UPLOAD_COVERAGE:-false}" = "true" ]; then
  echo ""
  echo "=========================================="
  echo "  Uploading coverage reports"
  echo "=========================================="

  # Build a descriptive flag name for matrix identification
  FLAG_NAME="py${PYTHON_VERSION//./}-${DB_BACKEND:-default}"

  # Upload to Codecov
  echo "Uploading to Codecov with flag: ${FLAG_NAME}"
  if command -v codecov &>/dev/null; then
    codecov --file coverage.xml --flags "${FLAG_NAME}" --name "${FLAG_NAME}" || true
  else
    pip install codecov
    codecov --file coverage.xml --flags "${FLAG_NAME}" --name "${FLAG_NAME}" || true
  fi

  # Upload to Coveralls
  echo "Uploading to Coveralls with flag: ${FLAG_NAME}"
  COVERALLS_FLAG_NAME="${FLAG_NAME}" coveralls || true

  echo "Coverage upload completed (flag: ${FLAG_NAME})"
else
  echo ""
  echo "Skipping coverage upload (UPLOAD_COVERAGE=${UPLOAD_COVERAGE:-false})"
fi
