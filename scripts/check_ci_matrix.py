#!/usr/bin/env python3
# coding: utf-8
"""Self-check that the GitHub Actions test matrix covers every required combination.

The authoritative list of combinations lives in ``.github/ci-matrix.yml``.
``.github/workflows/ci.yml`` realizes those combinations across its backend jobs
(sqlite / postgresql / mysql). This script asserts the two never drift:

* every required combination is realized by some job  (nothing dropped),
* no job realizes a combination that is not required  (nothing stray),
* no combination is realized by two jobs              (no duplicates),
* each job only realizes combinations for its own database backend.

It is run by the ``matrix-check`` CI job and exits non-zero (printing a diff) on
any mismatch, so a pull request cannot silently lose a key combination.
"""
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required to run this check: pip install pyyaml")


REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MANIFEST = REPO_ROOT / ".github" / "ci-matrix.yml"

# A job is a "test job" iff one of its steps invokes the shared composite action.
RUN_TESTS_ACTION = "./.github/actions/run-tests"


def as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def normalize(combo, source):
    """Reduce a raw mapping to a hashable (python, scrapyd, database, data_path) tuple."""
    if not isinstance(combo, dict):
        sys.exit("%s: expected a mapping, got %r" % (source, combo))
    for required_field in ("python", "database"):
        if required_field not in combo:
            sys.exit("%s: combination is missing required '%s': %r"
                     % (source, required_field, combo))
    return (
        str(combo["python"]),
        str(combo.get("scrapyd", "pip")),
        str(combo["database"]),
        as_bool(combo.get("data_path", False)),
    )


def fmt(combo):
    return "python=%s scrapyd=%s database=%s data_path=%s" % combo


def load_yaml(path):
    if not path.is_file():
        sys.exit("File not found: %s" % path)
    with open(str(path)) as handle:
        return yaml.safe_load(handle)


def is_test_job(job):
    for step in job.get("steps", []) or []:
        if isinstance(step, dict) and str(step.get("uses", "")).strip() == RUN_TESTS_ACTION:
            return True
    return False


def job_backend(job):
    """Infer a job's database backend from its declared service containers."""
    services = job.get("services") or {}
    images = " ".join(str((svc or {}).get("image", "")) for svc in services.values())
    if "postgres" in images:
        return "postgresql"
    if "mysql" in images:
        return "mysql"
    if services:
        return "unknown"
    return "sqlite"


def job_includes(job):
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    return matrix.get("include") or []


def main():
    workflow = load_yaml(WORKFLOW)
    manifest = load_yaml(MANIFEST)

    required = manifest.get("required_combinations")
    if not required:
        sys.exit("%s: 'required_combinations' is empty or missing" % MANIFEST)
    required_set = {normalize(combo, MANIFEST.name) for combo in required}

    jobs = workflow.get("jobs") or {}
    test_jobs = {name: job for name, job in jobs.items() if is_test_job(job)}
    if not test_jobs:
        sys.exit("%s: found no jobs using %s" % (WORKFLOW, RUN_TESTS_ACTION))

    realized = {}  # combo tuple -> job name that realizes it
    errors = []
    for name, job in sorted(test_jobs.items()):
        backend = job_backend(job)
        includes = job_includes(job)
        if not includes:
            errors.append("job '%s' uses %s but declares no strategy.matrix.include"
                          % (name, RUN_TESTS_ACTION))
            continue
        for raw in includes:
            combo = normalize(raw, "job '%s'" % name)
            if backend != "unknown" and combo[2] != backend:
                errors.append("job '%s' (backend=%s) lists a %s combination: %s"
                              % (name, backend, combo[2], fmt(combo)))
            if combo in realized:
                errors.append("duplicate combination in jobs '%s' and '%s': %s"
                              % (realized[combo], name, fmt(combo)))
            else:
                realized[combo] = name

    for combo in sorted(required_set - set(realized)):
        errors.append("MISSING (required but realized by no job): %s" % fmt(combo))
    for combo in sorted(set(realized) - required_set):
        errors.append("EXTRA (realized by job '%s' but not required): %s"
                      % (realized[combo], fmt(combo)))

    if errors:
        print("CI matrix self-check FAILED:\n")
        for err in errors:
            print("  - %s" % err)
        print("\nReconcile .github/ci-matrix.yml and .github/workflows/ci.yml so they agree.")
        return 1

    print("OK: %d combinations covered; ci.yml and ci-matrix.yml agree.\n"
          % len(required_set))
    for combo in sorted(realized):
        print("  - %-58s [job: %s]" % (fmt(combo), realized[combo]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
