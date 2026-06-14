#!/usr/bin/env python3
"""
validate-matrix.py — CI Matrix Coverage Validator

Parses .github/workflows/ci.yml and verifies that all required
(python-version, scrapyd-variant, db-backend) combinations are present.

Run locally:
    pip install pyyaml
    python scripts/ci/validate-matrix.py

Run in CI:
    Added as a pre-check step in the validate-matrix job.

Exit code 0 = all required combos covered. Exit code 1 = gaps found.
"""
import os
import sys
from itertools import product

# ── Required coverage dimensions ────────────────────────────────────────

PYTHON_VERSIONS = ["3.8", "3.9", "3.10", "3.11", "3.12", "3.13"]
SCRAPYD_VARIANTS = ["default", "v1.4.3", "git"]
DB_BACKENDS = ["default", "postgresql", "mysql", "sqlite-custom"]

# Each tuple is a (python, scrapyd_variant, db_backend) scenario
# that MUST appear in the matrix. Keep this list in sync with ci.yml.
REQUIRED_COMBOS = [
    # ── Vanilla Python version sweep (default scrapyd, default db) ──
    ("3.8",  "default", "default"),
    ("3.9",  "default", "default"),
    ("3.10", "default", "default"),
    ("3.11", "default", "default"),
    ("3.12", "default", "default"),
    ("3.13", "default", "default"),

    # ── Scrapyd version pinning ──
    ("3.9",  "v1.4.3", "default"),
    ("3.12", "v1.4.3", "default"),

    # ── Git HEAD installs with DB backends ──
    ("3.10", "git",    "postgresql"),
    ("3.10", "git",    "mysql"),

    # ── Database backend coverage (on Python 3.10) ──
    ("3.10", "default", "postgresql"),
    ("3.10", "default", "mysql"),
    ("3.10", "default", "sqlite-custom"),
]


# ── Parse the actual matrix from the workflow file ──────────────────────

def parse_matrix_from_workflow(path):
    """
    Extract (python, scrapyd_variant, db_backend) tuples from ci.yml.
    Handles both base matrix cross-product and explicit include entries.
    """
    import yaml

    with open(path) as f:
        wf = yaml.safe_load(f)

    test_job = wf["jobs"]["test"]
    strategy = test_job["strategy"]["matrix"]

    combos = set()

    # Base matrix: cross-product of top-level dimensions
    base_py = strategy.get("python-version", [])
    base_sv = strategy.get("scrapyd-variant", ["default"])
    base_db = strategy.get("db-backend", ["default"])

    # Ensure lists
    if not isinstance(base_py, list):
        base_py = [base_py]
    if not isinstance(base_sv, list):
        base_sv = [base_sv]
    if not isinstance(base_db, list):
        base_db = [base_db]

    for py, sv, db in product(base_py, base_sv, base_db):
        combos.add((str(py), sv, db))

    # Exclude entries (if any)
    for entry in strategy.get("exclude", []):
        py = str(entry.get("python-version", ""))
        sv = entry.get("scrapyd-variant", "default")
        db = entry.get("db-backend", "default")
        combos.discard((py, sv, db))

    # Include entries override/add specific combos
    for entry in strategy.get("include", []):
        py = str(entry.get("python-version", ""))
        sv = entry.get("scrapyd-variant", "default")
        db = entry.get("db-backend", "default")
        if py:
            combos.add((py, sv, db))

    return combos


# ── Validate ────────────────────────────────────────────────────────────

def validate():
    # Resolve workflow path relative to this script's location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    workflow_path = os.path.join(project_root, ".github", "workflows", "ci.yml")

    try:
        actual_combos = parse_matrix_from_workflow(workflow_path)
    except FileNotFoundError:
        print(f"ERROR: {workflow_path} not found")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR parsing workflow: {e}")
        sys.exit(1)

    required_set = set(REQUIRED_COMBOS)
    missing = required_set - actual_combos
    extra = actual_combos - required_set

    print("=" * 60)
    print("  CI Matrix Validation Report")
    print("=" * 60)
    print(f"  Jobs defined:   {len(actual_combos)}")
    print(f"  Required:       {len(required_set)}")
    print(f"  Missing:        {len(missing)}")
    print(f"  Extra:          {len(extra)}")
    print("=" * 60)
    print()

    ok = True

    # ── Check missing required combos ──
    if missing:
        print("FAIL: Missing required combinations:")
        for combo in sorted(missing):
            print(f"  - Python {combo[0]}, Scrapyd {combo[1]}, DB {combo[2]}")
        ok = False
    else:
        print("PASS: All required combinations are covered")

    # ── Show extra combos (informational) ──
    if extra:
        print(f"\nINFO: Extra combinations ({len(extra)}):")
        for combo in sorted(extra):
            print(f"  + Python {combo[0]}, Scrapyd {combo[1]}, DB {combo[2]}")

    # ── Dimensional coverage check ──
    print("\n--- Dimensional Coverage ---")
    actual_pys = {c[0] for c in actual_combos}
    actual_svs = {c[1] for c in actual_combos}
    actual_dbs = {c[2] for c in actual_combos}

    for dim_name, required, actual in [
        ("Python versions", set(PYTHON_VERSIONS), actual_pys),
        ("Scrapyd variants", set(SCRAPYD_VARIANTS), actual_svs),
        ("DB backends", set(DB_BACKENDS), actual_dbs),
    ]:
        uncovered = required - actual
        if uncovered:
            print(f"  WARN: {dim_name} not fully covered: {sorted(uncovered)}")
            ok = False
        else:
            print(f"  PASS: {dim_name}: fully covered")

    # ── Summary ──
    print()
    if ok:
        print("RESULT: Matrix validation PASSED")
    else:
        print("RESULT: Matrix validation FAILED — fix the gaps above")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    validate()
