#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# run-tests.sh — Run flake8 lint checks + pytest with coverage
#
# Env vars consumed:
#   ALLURE_ENABLED  — true | false (default: false)
#
# Steps:
#   1. flake8 critical errors (E9,F63,F7,F82) — must pass
#   2. coverage erase + coverage run pytest with optional Allure
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

echo "=========================================="
echo "  Flake8 critical error checks"
echo "=========================================="
flake8 . --count --exclude=./venv*,.git,./build,./dist \
  --select=E9,F63,F7,F82 --show-source --statistics

echo ""
echo "=========================================="
echo "  Running tests with coverage"
echo "=========================================="
coverage erase

PYTEST_ARGS=(
  -s -vv -l
  --disable-warnings
  --junitxml=test-results.xml
  tests
)

if [ "${ALLURE_ENABLED:-false}" = "true" ]; then
  PYTEST_ARGS+=(--alluredir=allure-results)
  echo "Allure reporting enabled — writing to allure-results/"
fi

echo "pytest args: ${PYTEST_ARGS[*]}"
echo ""
coverage run --source=scrapydweb -m pytest "${PYTEST_ARGS[@]}"
