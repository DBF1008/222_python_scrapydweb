# ScrapydWeb release tooling.
# These targets mirror the CI release pipeline so you can validate
# locally before pushing a tag.  Run ``make release`` as a full
# pre-flight check.
#
# Prerequisites:  pip install build twine
#
# Override the interpreter with:  make PYTHON=python3.11 release

SHELL       := /bin/bash
PYTHON      ?= python3
VERSION     := $(shell $(PYTHON) -c "exec(open('scrapydweb/__version__.py').read()); print(__version__)")
SDIST       := dist/scrapydweb-$(VERSION).tar.gz
WHEEL       := dist/scrapydweb-$(VERSION)-py3-none-any.whl
SMOKE_VENV  := .venv-release

SDIST_REQUIRED := \
	scrapydweb/__version__.py \
	scrapydweb/__init__.py \
	scrapydweb/run.py \
	setup.py \
	README.md \
	HISTORY.md \
	requirements.txt \
	MANIFEST.in

WHEEL_REQUIRED := \
	scrapydweb/__version__.py \
	scrapydweb/__init__.py \
	scrapydweb/run.py \
	scrapydweb/default_settings.py

.PHONY: help check-version clean build validate smoke-test release

help:  ## Show this help message
	@echo "ScrapydWeb release tooling (current version: $(VERSION))"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# check-version: verify version consistency across all tracked files
# ---------------------------------------------------------------------------
check-version:  ## Verify version consistency across __version__.py, HISTORY.md, and setup.py
	@echo "==> Checking version $(VERSION) ..."
	@test -n "$(VERSION)" || { echo "ERROR: could not parse version from __version__.py"; exit 1; }
	@# HISTORY.md uses RST headings like "1.6.0 (2025-02-16)" (no # prefix)
	@grep -qE "^$(subst .,\.,$(VERSION)) \([0-9]{4}-[0-9]{2}-[0-9]{2}\)" HISTORY.md || \
	  { echo "ERROR: HISTORY.md has no entry for $(VERSION)"; exit 1; }
	@SETUP_VER=$$($(PYTHON) setup.py --version 2>/dev/null); \
	  test "$$SETUP_VER" = "$(VERSION)" || \
	  { echo "ERROR: setup.py reports $$SETUP_VER but __version__.py says $(VERSION)"; exit 1; }
	@echo "    Version $(VERSION) is consistent across all files."

# ---------------------------------------------------------------------------
# clean: remove all build artifacts
# ---------------------------------------------------------------------------
clean:  ## Remove build artifacts and temporary venv
	rm -rf dist/ build/ *.egg-info scrapydweb.egg-info $(SMOKE_VENV)/

# ---------------------------------------------------------------------------
# build: clean + produce sdist and wheel
# ---------------------------------------------------------------------------
build: clean check-version  ## Build sdist and wheel via python -m build
	@echo "==> Building artifacts ..."
	$(PYTHON) -m build
	@echo "    Built: $(SDIST)"
	@echo "    Built: $(WHEEL)"

# ---------------------------------------------------------------------------
# validate: check-version + build + twine check + content verification
# ---------------------------------------------------------------------------
validate: build  ## Validate artifacts (twine check + content inspection)
	@echo "==> Running twine check ..."
	twine check dist/*
	@echo "==> Verifying sdist contents ..."
	@tar tzf $(SDIST) > /tmp/_sdist_contents.txt
	@for f in $(SDIST_REQUIRED); do \
	  if ! grep -q "$$f" /tmp/_sdist_contents.txt; then \
	    echo "ERROR: sdist is missing $$f"; exit 1; \
	  fi; \
	done
	@rm -f /tmp/_sdist_contents.txt
	@echo "    sdist OK — all required files present."
	@echo "==> Verifying wheel contents ..."
	@unzip -l $(WHEEL) > /tmp/_wheel_contents.txt
	@for f in $(WHEEL_REQUIRED); do \
	  if ! grep -q "$$f" /tmp/_wheel_contents.txt; then \
	    echo "ERROR: wheel is missing $$f"; exit 1; \
	  fi; \
	done
	@rm -f /tmp/_wheel_contents.txt
	@echo "    wheel OK — all required files present."
	@echo "==> All validations passed for $(VERSION)."

# ---------------------------------------------------------------------------
# smoke-test: install in an isolated venv and verify import + CLI
# ---------------------------------------------------------------------------
smoke-test: build  ## Install wheel in a temporary venv and run smoke tests
	@echo "==> Creating smoke-test venv ..."
	$(PYTHON) -m venv $(SMOKE_VENV)
	$(SMOKE_VENV)/bin/pip install --quiet --upgrade pip
	@echo "==> Installing wheel ..."
	$(SMOKE_VENV)/bin/pip install --quiet $(WHEEL)
	@echo "==> Checking import and version ..."
	$(SMOKE_VENV)/bin/python -c "\
import scrapydweb; \
assert scrapydweb.__version__ == '$(VERSION)', \
  f'Version mismatch: {scrapydweb.__version__} != $(VERSION)'; \
print(f'    import scrapydweb OK — version {scrapydweb.__version__}')"
	@echo "==> Checking CLI entry point ..."
	$(SMOKE_VENV)/bin/scrapydweb --help > /dev/null
	@echo "    scrapydweb --help OK."
	@echo "==> Checking heavy dependency imports ..."
	$(SMOKE_VENV)/bin/python -c "from scrapydweb.utils import db; print('    scrapydweb.utils.db OK')"
	@echo "==> Cleaning up smoke-test venv ..."
	rm -rf $(SMOKE_VENV)
	@echo "==> Smoke test passed."

# ---------------------------------------------------------------------------
# release: all-in-one pre-release check (alias for validate + smoke-test)
# ---------------------------------------------------------------------------
release: validate smoke-test  ## Full pre-release dry run (validate + build + smoke-test)
	@echo ""
	@echo "============================================"
	@echo "  Release $(VERSION) is ready!"
	@echo ""
	@echo "  Next steps:"
	@echo "    git add -A && git commit -m 'Release v$(VERSION)'"
	@echo "    git tag v$(VERSION)"
	@echo "    git push origin main --tags"
	@echo "============================================"
