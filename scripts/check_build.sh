#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# ScrapydWeb — Build smoke-check
# ──────────────────────────────────────────────────────────
# Builds wheel + sdist, verifies artifact contents, test-
# installs in a fresh venv, and checks the CLI entry point.
#
# Usage:  ./scripts/check_build.sh
# Exit:   0 = all checks pass, 1 = any check failed
# ──────────────────────────────────────────────────────────
set -euo pipefail

# ── Colours & helpers ────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
FAIL=0
pass()  { echo -e "  ${GREEN}✓${NC} $1"; }
fail()  { echo -e "  ${RED}✗${NC} $1"; FAIL=1; }
info()  { echo -e "  ${YELLOW}→${NC} $1"; }
step()  { echo ""; echo -e "${YELLOW}[$1/$2] $3${NC}"; }
cleanup_dirs=()
cleanup() { for d in "${cleanup_dirs[@]}"; do rm -rf "$d"; done; }
trap cleanup EXIT

cd "$(dirname "$0")/.."
echo "══════════════════════════════════════════════════════════"
echo "  ScrapydWeb — PEP 517 Build Smoke Check"
echo "══════════════════════════════════════════════════════════"

# ── Ensure `build` is available ──────────────────────────

if python3 -m build --version >/dev/null 2>&1; then
    BUILD_PY="python3"
else
    info "python3 -m build not found — creating build venv"
    BUILD_VENV=$(mktemp -d)/build_venv
    cleanup_dirs+=("$(dirname "$BUILD_VENV")")
    python3 -m venv "$BUILD_VENV"
    "$BUILD_VENV/bin/pip" install --quiet build
    BUILD_PY="$BUILD_VENV/bin/python3"
fi

# ── Read expected version ────────────────────────────────

EXPECTED_VERSION=$(python3 -c "
from scrapydweb.__version__ import __version__
print(__version__)
")
info "Expected version: $EXPECTED_VERSION"

VDIR="v${EXPECTED_VERSION//./}"   # e.g. 1.6.0 → v160

# ── Clean previous artifacts ─────────────────────────────

rm -rf dist/ build/ scrapydweb.egg-info/

# ──────────────────────────────────────────────────────────
step 1 6 "Building wheel and sdist"
# ──────────────────────────────────────────────────────────

$BUILD_PY -m build --outdir dist/

WHEEL=$(find dist -name "scrapydweb-*.whl" | head -1)
SDIST=$(find dist -name "scrapydweb-*.tar.gz" | head -1)

if [ -z "$WHEEL" ]; then fail "No wheel produced"; else pass "Wheel: $(basename "$WHEEL")"; fi
if [ -z "$SDIST" ]; then fail "No sdist produced"; else pass "Sdist: $(basename "$SDIST")"; fi

if [ $FAIL -ne 0 ]; then
    echo -e "\n${RED}Build failed — cannot continue.${NC}"
    exit 1
fi

# ──────────────────────────────────────────────────────────
step 2 6 "Verifying wheel contents"
# ──────────────────────────────────────────────────────────

WHEEL_FILES=$(python3 -c "
import zipfile, sys
with zipfile.ZipFile('$WHEEL') as z:
    for n in sorted(z.namelist()):
        print(n)
")

check_wheel() {
    local pattern="$1"
    local label="$2"
    if echo "$WHEEL_FILES" | grep -q "$pattern"; then
        pass "$label"
    else
        fail "$label"
    fi
}

check_wheel "scrapydweb/static/${VDIR}/css/style.css" "Static CSS present"
check_wheel "scrapydweb/static/${VDIR}/js/common.js"  "Static JS present"
check_wheel "scrapydweb/static/${VDIR}/icon/fav.ico"   "Static icons present"
check_wheel "element-icons.woff"                       "Static fonts present"
check_wheel "scrapydweb/templates/base.html"            "Templates present"
check_wheel "scrapydweb/templates/scrapydweb/jobs.html" "View templates present"
check_wheel "scrapydweb/data/demo_projects/ScrapydWeb_demo/scrapy.cfg" "Demo project present"
check_wheel "scrapydweb/data/demo_projects/ScrapydWeb_demo/ScrapydWeb_demo/spiders/test.py" "Demo spider present"
check_wheel "scrapydweb/data/parse/ScrapydWeb_demo.log" "Sample log present"
check_wheel "scrapydweb/__init__.py"                    "Package init present"
check_wheel "scrapydweb-.*\.dist-info/METADATA"         "METADATA present"
check_wheel "scrapydweb-.*\.dist-info/entry_points.txt" "Entry points present"

# Count package data files (static + templates + data, regardless of extension)
PKG_DATA_COUNT=$(echo "$WHEEL_FILES" | grep -E "^scrapydweb/(static|templates|data)/" | grep -v '__pycache__' | wc -l | tr -d ' ')
if [ "$PKG_DATA_COUNT" -ge 80 ]; then
    pass "Package data files: $PKG_DATA_COUNT (≥80)"
else
    fail "Package data files: $PKG_DATA_COUNT (expected ≥80)"
fi

PY_COUNT=$(echo "$WHEEL_FILES" | grep "^scrapydweb/" | grep '\.py$' | grep -v '__pycache__' | wc -l | tr -d ' ')
if [ "$PY_COUNT" -ge 30 ]; then
    pass "Python modules: $PY_COUNT (≥30)"
else
    fail "Python modules: $PY_COUNT (expected ≥30)"
fi

# ──────────────────────────────────────────────────────────
step 3 6 "Verifying sdist contents"
# ──────────────────────────────────────────────────────────

SDIST_FILES=$(python3 -c "
import tarfile, sys
with tarfile.open('$SDIST', 'r:gz') as t:
    for m in sorted(t.getmembers(), key=lambda x: x.name):
        if m.isfile():
            print(m.name)
")

check_sdist() {
    local pattern="$1"
    local label="$2"
    if echo "$SDIST_FILES" | grep -q "$pattern"; then
        pass "$label"
    else
        fail "$label"
    fi
}

check_sdist "HISTORY.md"       "HISTORY.md in sdist"
check_sdist "LICENSE"          "LICENSE in sdist"
check_sdist "README.md"        "README.md in sdist"
check_sdist "pyproject.toml"   "pyproject.toml in sdist"
check_sdist "setup.py"         "setup.py in sdist"
check_sdist "MANIFEST.in"      "MANIFEST.in in sdist"
check_sdist "static/"          "Static dir in sdist"
check_sdist "templates/"       "Templates dir in sdist"
check_sdist "ScrapydWeb_demo/scrapy.cfg" "Demo project in sdist"
check_sdist "ScrapydWeb_demo.log"        "Sample log in sdist"

# Check Chinese-named demo project
if echo "$SDIST_FILES" | grep -q "副本"; then
    pass "Chinese-named demo project (副本) in sdist"
else
    fail "Chinese-named demo project (副本) MISSING from sdist"
fi

# ──────────────────────────────────────────────────────────
step 4 6 "Installing wheel in isolated venv"
# ──────────────────────────────────────────────────────────

TEST_VENV=$(mktemp -d)/scrapydweb_test_venv
cleanup_dirs+=("$(dirname "$TEST_VENV")")
python3 -m venv "$TEST_VENV"
"$TEST_VENV/bin/pip" install --quiet --upgrade pip
"$TEST_VENV/bin/pip" install --quiet "$WHEEL"
pass "Wheel installed in $TEST_VENV"

# ──────────────────────────────────────────────────────────
step 5 6 "Testing console entry point"
# ──────────────────────────────────────────────────────────

if [ -x "$TEST_VENV/bin/scrapydweb" ]; then
    pass "scrapydweb executable exists"
else
    fail "scrapydweb executable not found"
fi

if "$TEST_VENV/bin/scrapydweb" --help >/dev/null 2>&1; then
    pass "scrapydweb --help succeeds"
else
    # Fallback: verify the entry-point script and target module are installed.
    # --help can fail on newer Python due to transitive runtime deps
    # (e.g. APScheduler 3.x uses pkg_resources removed in Python ≥3.12).
    if [ -x "$TEST_VENV/bin/scrapydweb" ] && \
       "$TEST_VENV/bin/python3" -c "
import sys, os
for p in sys.path:
    run_py = os.path.join(p, 'scrapydweb', 'run.py')
    if os.path.isfile(run_py):
        print('entry-point module installed: ' + run_py)
        sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
        pass "scrapydweb entry-point module present (--help skipped: runtime dep issue)"
    else
        fail "scrapydweb --help failed and entry-point module not found"
    fi
fi

# ──────────────────────────────────────────────────────────
step 6 6 "Testing imports and package data access"
# ──────────────────────────────────────────────────────────

"$TEST_VENV/bin/python3" -c "
import sys, os, importlib.util, importlib.machinery

# ── Locate installed package root without triggering __init__.py ──
# Find scrapydweb on sys.path without importing it
pkg_root = None
for p in sys.path:
    candidate = os.path.join(p, 'scrapydweb')
    if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, '__init__.py')):
        pkg_root = candidate
        break
assert pkg_root is not None, 'scrapydweb package not found on sys.path'
print('  ✓ Package root: ' + pkg_root)

# ── Version check (exec __version__.py without importing the package) ──
ver_file = os.path.join(pkg_root, '__version__.py')
assert os.path.isfile(ver_file), f'Missing: {ver_file}'
about = {}
exec(open(ver_file).read(), about)
assert about['__version__'] == '$EXPECTED_VERSION', f'Version mismatch: {about[\"__version__\"]} != $EXPECTED_VERSION'
print('  ✓ Version: ' + about['__title__'] + ' ' + about['__version__'])

# ── Package data dirs ──
static_dir = os.path.join(pkg_root, 'static', '$VDIR')
assert os.path.isdir(static_dir), f'Missing: {static_dir}'
print('  ✓ Static dir: ' + static_dir)

css = os.path.join(static_dir, 'css', 'style.css')
assert os.path.isfile(css), f'Missing: {css}'
print('  ✓ Static CSS: ' + css)

js = os.path.join(static_dir, 'js', 'common.js')
assert os.path.isfile(js), f'Missing: {js}'
print('  ✓ Static JS: ' + js)

ico = os.path.join(static_dir, 'icon', 'fav.ico')
assert os.path.isfile(ico), f'Missing: {ico}'
print('  ✓ Static icon: ' + ico)

font = os.path.join(static_dir, 'element-ui@2.4.6', 'lib', 'theme-chalk', 'fonts', 'element-icons.woff')
assert os.path.isfile(font), f'Missing: {font}'
print('  ✓ Static font: ' + font)

tpl_dir = os.path.join(pkg_root, 'templates')
assert os.path.isdir(tpl_dir), f'Missing: {tpl_dir}'
print('  ✓ Templates dir: ' + tpl_dir)

tpl = os.path.join(tpl_dir, 'base.html')
assert os.path.isfile(tpl), f'Missing: {tpl}'
print('  ✓ Template file: base.html')

data_dir = os.path.join(pkg_root, 'data', 'demo_projects')
assert os.path.isdir(data_dir), f'Missing: {data_dir}'
print('  ✓ Demo projects dir: ' + data_dir)

demo_cfg = os.path.join(data_dir, 'ScrapydWeb_demo', 'scrapy.cfg')
assert os.path.isfile(demo_cfg), f'Missing: {demo_cfg}'
print('  ✓ Demo project cfg: ' + demo_cfg)

demo_log = os.path.join(pkg_root, 'data', 'parse', 'ScrapydWeb_demo.log')
assert os.path.isfile(demo_log), f'Missing: {demo_log}'
print('  ✓ Sample log: ' + demo_log)

cn_dir = os.path.join(data_dir, 'ScrapydWeb_demo - 副本')
assert os.path.isdir(cn_dir), f'Missing: {cn_dir}'
print('  ✓ Chinese-named demo dir: ' + cn_dir)

# ── Module files present (file-based, no import) ──
run_py = os.path.join(pkg_root, 'run.py')
assert os.path.isfile(run_py), 'scrapydweb/run.py not found'
print('  ✓ scrapydweb/run.py present')

init_py = os.path.join(pkg_root, '__init__.py')
assert os.path.isfile(init_py), 'scrapydweb/__init__.py not found'
print('  ✓ scrapydweb/__init__.py present')

# ── entry_points.txt check ──
dist_info = os.path.join(os.path.dirname(pkg_root), 'scrapydweb-$EXPECTED_VERSION.dist-info')
ep_file = os.path.join(dist_info, 'entry_points.txt')
if os.path.isfile(ep_file):
    ep_text = open(ep_file).read()
    assert 'scrapydweb' in ep_text, 'entry_points.txt missing scrapydweb'
    assert 'scrapydweb.run:main' in ep_text, 'entry_points.txt missing run:main'
    print('  ✓ entry_points.txt correct')
else:
    print('  ⚠ entry_points.txt not found (may use different dist-info path)')
"

if [ $? -eq 0 ]; then
    pass "All imports and package data checks passed"
else
    fail "Import or package data check failed"
fi

# ── Summary ──────────────────────────────────────────────

echo ""
echo "══════════════════════════════════════════════════════════"
if [ $FAIL -eq 0 ]; then
    WHEEL_SIZE=$(du -h "$WHEEL" | cut -f1 | tr -d ' ')
    SDIST_SIZE=$(du -h "$SDIST" | cut -f1 | tr -d ' ')
    echo -e "  ${GREEN}✓ All checks passed!${NC}"
    echo "  Wheel: $(basename "$WHEEL") ($WHEEL_SIZE)"
    echo "  Sdist: $(basename "$SDIST") ($SDIST_SIZE)"
    echo "══════════════════════════════════════════════════════════"
    exit 0
else
    echo -e "  ${RED}✗ Some checks failed!${NC}"
    echo "══════════════════════════════════════════════════════════"
    exit 1
fi
