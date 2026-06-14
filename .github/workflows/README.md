# ScrapydWeb CI

ScrapydWeb's tests run on **GitHub Actions** (`.github/workflows/ci.yml`). This
replaces the former `.circleci/config.yml`, whose one giant `&test-template`
anchor was copied by every job.

## Design

```
.github/
  actions/run-tests/action.yml   ← reusable entry point (composite action)
  workflows/ci.yml               ← matrix-check + sqlite / postgresql / mysql jobs
  ci-matrix.yml                  ← single source of truth: required combinations
scripts/check_ci_matrix.py       ← self-check run by the matrix-check job
```

* **One entry point.** Every combination — install, Scrapyd-variant selection,
  Scrapyd launch and the `flake8` + `coverage`/`pytest` run — flows through the
  composite action `./.github/actions/run-tests`. The workflow jobs only supply
  inputs; no test logic is duplicated.

* **Grouped by backend.** Service containers (PostgreSQL, MySQL) can only be
  declared per job, so the matrix is split into three jobs — `sqlite` (no
  service), `postgresql` (Postgres service) and `mysql` (MySQL service) — each
  driving a Python matrix and all calling the same action.

* **Self-checking matrix.** `.github/ci-matrix.yml` lists every required
  combination once. The `matrix-check` job runs `scripts/check_ci_matrix.py`,
  which auto-discovers the test jobs (any job that uses the composite action),
  collects their `strategy.matrix.include` entries and fails if they don't match
  the manifest exactly (missing, extra, duplicated, or backend-mismatched
  combinations). The three test jobs `needs: matrix-check`, so drift fails fast
  before any compute is spent.

## Combinations and their CircleCI origin

| python | scrapyd | database   | data_path | was (CircleCI job)    |
|--------|---------|------------|-----------|-----------------------|
| 3.8    | pip     | sqlite     | false     | py38                  |
| 3.9    | pip     | sqlite     | false     | py39                  |
| 3.9    | v143    | sqlite     | false     | py39-scrapyd-v143     |
| 3.10   | pip     | sqlite     | true      | py310-sqlite          |
| 3.10   | pip     | postgresql | false     | py310-postgresql      |
| 3.10   | git     | postgresql | false     | py310-git-postgresql  |
| 3.10   | pip     | mysql      | false     | py310-mysql           |
| 3.10   | git     | mysql      | false     | py310-git-mysql       |
| 3.11   | pip     | sqlite     | false     | py311                 |
| 3.12   | pip     | sqlite     | false     | py312                 |
| 3.12   | v143    | sqlite     | false     | py312-scrapyd-v143    |
| 3.13   | pip     | sqlite     | false     | py313                 |

`scrapyd`: `pip` = latest from `requirements-tests.txt`; `v143` = `scrapyd==1.4.3`;
`git` = scrapy + scrapyd + logparser from git HEAD.

Python 2.7 / 3.6 / 3.7 were already commented out in CircleCI and are not carried over.

## Adding or removing a combination

1. Edit the list in **`.github/ci-matrix.yml`**.
2. Edit the matching job's `strategy.matrix.include` in **`.github/workflows/ci.yml`**
   (use the job whose backend matches the combination's `database`).
3. `python scripts/check_ci_matrix.py` must print `OK`. The `matrix-check` job
   enforces this on every push/PR, so the two files can't silently diverge.

## Conventions

* **Scrapyd** runs with basic auth `admin` / `12345` on `127.0.0.1:6800`
  (required by `tests/conftest.py`).
* **Databases are created by the app** at import time when
  `SCRAPYDWEB_TESTMODE=True` (`scrapydweb/utils/setup_database.py`). CI only
  provides a reachable server; it does not run `CREATE DATABASE`.
* **PostgreSQL** uses `POSTGRES_HOST_AUTH_METHOD: trust`, matching the original
  CircleCI image where the test connection string carried a bogus password.
* **MySQL** connects as `root` / `rootpw` over TCP (`127.0.0.1:3306`).
* `DATABASE_URL` / `DATA_PATH` are derived from the action inputs in its
  *Resolve test environment* step.

## Optional knobs

* **`TEST_ON_CIRCLECI`** — left unset (matches CircleCI, which never set it). It
  only enables a stricter data-path assertion (`tests/test_system.py`) and a
  debug log; set it to `true` in the action's resolve-env step if you want the
  stricter check.
* **DB image versions** — pinned to `postgres:9.6` / `mysql:5.7` for fidelity
  with the suite's original targets; bump the `image:` tags in `ci.yml` to test
  newer engines.
* **Coverage** — `codecov/codecov-action` runs non-blocking (needs the
  `CODECOV_TOKEN` secret). Coveralls is not wired up; re-add it as a step if
  desired. Raw `allure-results` and `htmlcov` are uploaded as artifacts (the
  heavy Java/Allure-CLI HTML generation from CircleCI was dropped).
