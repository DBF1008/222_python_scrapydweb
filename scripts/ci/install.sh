#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# install.sh — Install project dependencies with optional variant overrides
#
# Env vars consumed:
#   SCRAPYD_VARIANT  — default | v1.4.3 | git
#
# Installs:
#   1. Base: requirements.txt + requirements-tests.txt
#   2. Variant override (if any)
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

echo "=========================================="
echo "  Installing base dependencies"
echo "=========================================="

pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-tests.txt

case "${SCRAPYD_VARIANT:-default}" in
  git)
    echo ""
    echo "=========================================="
    echo "  Installing Scrapy/Scrapyd/LogParser from git HEAD"
    echo "=========================================="
    pip install -U git+https://github.com/scrapy/scrapy.git
    pip install -U git+https://github.com/scrapy/scrapyd.git
    pip install -U git+https://github.com/my8100/logparser.git
    ;;
  v1.4.3)
    echo ""
    echo "=========================================="
    echo "  Pinning scrapyd==1.4.3"
    echo "=========================================="
    pip install scrapyd==1.4.3
    ;;
  default|"")
    echo ""
    echo "Using default package versions (no variant override)"
    ;;
  *)
    echo "::error::Unknown SCRAPYD_VARIANT: '${SCRAPYD_VARIANT}'. Expected: default|v1.4.3|git"
    exit 1
    ;;
esac

echo ""
echo "=========================================="
echo "  Installed packages"
echo "=========================================="
pip list
