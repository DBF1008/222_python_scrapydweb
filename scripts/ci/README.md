# CI Scripts

Reusable shell scripts for ScrapydWeb's CI pipeline. These scripts are called from `.github/workflows/ci.yml` but can also be run locally for debugging.

## Prerequisites

- Python 3.8+
- pip
- curl (for Scrapyd health check)
- nc / netcat (for database health checks)
- (For DB tests) PostgreSQL or MySQL running and accessible

## Quick Start — Local Testing

```bash
# Set required environment variables
export SCRAPYDWEB_TESTMODE=True

# Optional: choose a database backend (default: SQLite)
export DB_BACKEND=default       # or: postgresql, mysql, sqlite-custom

# Optional: choose a Scrapyd variant (default: latest from PyPI)
export SCRAPYD_VARIANT=default  # or: v1.4.3, git

# Run the full pipeline
bash scripts/ci/setup-env.sh
bash scripts/ci/install.sh
bash scripts/ci/setup-db.sh     # Only needed for postgresql/mysql
bash scripts/ci/launch-scrapyd.sh
bash scripts/ci/run-tests.sh
bash scripts/ci/coverage-report.sh
```

## Script Reference

| Script | Purpose | Key Env Vars |
|--------|---------|-------------|
| `setup-env.sh` | Set `DATABASE_URL` and `DATA_PATH` based on backend type | `DB_BACKEND` |
| `install.sh` | Install `requirements.txt` + `requirements-tests.txt`, apply variant overrides | `SCRAPYD_VARIANT` |
| `setup-db.sh` | Create the 4 required databases for PostgreSQL or MySQL | `DB_BACKEND` |
| `launch-scrapyd.sh` | Write `scrapyd.conf` (admin:12345), launch Scrapyd, poll until ready | *(none)* |
| `run-tests.sh` | Run flake8 critical checks + pytest with coverage | `ALLURE_ENABLED` |
| `coverage-report.sh` | Generate coverage report/html/xml, optionally upload to Codecov/Coveralls | `UPLOAD_COVERAGE`, `DB_BACKEND`, `PYTHON_VERSION` |
| `validate-matrix.py` | Parse `.github/workflows/ci.yml` and verify matrix completeness | *(none)* |

## Environment Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `DB_BACKEND` | `default`, `postgresql`, `mysql`, `sqlite-custom` | `default` | Selects database backend |
| `SCRAPYD_VARIANT` | `default`, `v1.4.3`, `git` | `default` | Selects Scrapyd version/source |
| `ALLURE_ENABLED` | `true`, `false` | `false` | Enable Allure report generation |
| `UPLOAD_COVERAGE` | `true`, `false` | `false` | Upload coverage to Codecov/Coveralls |
| `PYTHON_VERSION` | e.g. `3.12` | *(auto)* | Used for coverage flag naming |
| `SCRAPYDWEB_TESTMODE` | `True` | — | Required by ScrapydWeb test suite |
| `DATABASE_URL` | Connection string | *(auto)* | Set by `setup-env.sh` |
| `DATA_PATH` | Directory path | *(auto)* | Set by `setup-env.sh` for sqlite-custom |

## Matrix Validation

```bash
# Install dependency
pip install pyyaml

# Run validation
python scripts/ci/validate-matrix.py
```

The validator checks that all required (Python version, Scrapyd variant, DB backend) combinations are present in the CI matrix. It exits with code 1 if any required combination is missing.

To add a new required combination, update the `REQUIRED_COMBOS` list in `validate-matrix.py` and add the corresponding entry to the `include` section in `.github/workflows/ci.yml`.
