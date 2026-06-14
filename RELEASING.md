# Releasing ScrapydWeb

ScrapydWeb is released by **pushing a Git tag**. A GitHub Actions pipeline
(`.github/workflows/release.yml`) then verifies the tag against the package
version, builds the distributions, validates their contents, smoke-tests them in
clean environments, and publishes to **TestPyPI first, then PyPI** — with a
manual approval gate before the real index.

The version lives in exactly one place — `scrapydweb/__version__.py` — which
`setup.py` reads at build time. Everything else (the tag, `HISTORY.md`, the
README badge) is checked against it.

---

## Pipeline at a glance

```
push tag vX.Y.Z
      │
      ▼
verify-version ─► build ─► smoke-test ─► publish-testpypi ─► verify-testpypi-install ─► publish-pypi
                                                                                         (manual approval)
```

Each stage gates the next (`needs:`). **If any stage fails, the chain stops and
nothing is published.**

| Stage | What it guarantees |
|-------|--------------------|
| `verify-version` | Tag == `scrapydweb/__version__.py`; `setup.py` still reads the version (not hardcoded); `HISTORY.md` has this version as its newest entry; README keeps the dynamic PyPI badge. |
| `build` | `python -m build` produces sdist + wheel; `twine check` passes; `release.verify_artifacts` confirms the artifacts carry the right version **and** every `MANIFEST.in` resource (static/, templates/, demo project, demo log, scrapy.cfg) plus the registered `scrapydweb` console script. |
| `smoke-test` | The wheel **and** the sdist each install into a clean venv and import; `__version__` matches; the console entry point is registered; packaged data files resolve on disk. |
| `publish-testpypi` | Uploads to TestPyPI over OIDC (idempotent via `skip-existing`). |
| `verify-testpypi-install` | Installs the *just-published* package from TestPyPI (deps from PyPI) and smoke-tests it — proves what was actually uploaded works. |
| `publish-pypi` | Uploads to PyPI over OIDC, **after** the `pypi` environment's required reviewer approves. |

---

## One-time setup

### 1. GitHub Environments

Create two environments (Settings → Environments):

- **`testpypi`** — no protection needed.
- **`pypi`** — add **Required reviewers** (the people allowed to approve a
  production release). This approval is the human gate and the primary
  pre-publish rollback control.

The environment **names must match** the Trusted Publisher config below.

### 2. OIDC Trusted Publishing (no secrets)

On **both** https://test.pypi.org and https://pypi.org, add a *Trusted Publisher*
for the `scrapydweb` project (PyPI → project → Publishing → Add a new publisher):

| Field | Value |
|-------|-------|
| Owner | `my8100` (the GitHub org/user) |
| Repository | `scrapydweb` |
| Workflow name | `release.yml` |
| Environment | `testpypi` (on TestPyPI) / `pypi` (on PyPI) |

No tokens are stored anywhere. The publish jobs request an OIDC token
(`permissions: id-token: write`) that PyPI validates against this config.

> **Token fallback (if you can't use OIDC yet):** create project-scoped API
> tokens, store them as environment secrets `TEST_PYPI_API_TOKEN` /
> `PYPI_API_TOKEN`, and pass `password: ${{ secrets.* }}` (with
> `repository-url`) to `pypa/gh-action-pypi-publish`. Rotate them regularly.

---

## Cutting a release

```bash
# 1. Bump the source-of-truth version and stage a HISTORY.md entry.
python -m release.bump_version 1.7.0 --write     # edits __version__.py + HISTORY.md
$EDITOR HISTORY.md                                # replace the TODO with real notes

# 2. Sanity-check consistency locally (optional but recommended).
python -m release.check_version --tag v1.7.0

# 3. Open a PR, get it reviewed, and merge to the default branch.

# 4. Tag the merge commit and push the tag.
git tag v1.7.0
git push origin v1.7.0

# 5. Watch the Actions run. When it reaches `publish-pypi`, approve the
#    `pypi` environment to release to PyPI.
```

A **manual dry run** (build + verify, no publish) is available via
*Actions → release → Run workflow*: set `ref` to an existing tag and leave
`dry_run` checked.

---

## Running the checks locally

```bash
# Version consistency (uses the repo files).
python -m release.check_version --tag v1.7.0

# Build, then verify artifact contents + version.
python -m build
python -m twine check dist/*
python -m release.verify_artifacts --tag v1.7.0 --dist dist

# Clean-venv smoke test (note: pin setuptools<81, see below).
python -m venv /tmp/venv
/tmp/venv/bin/python -m pip install "setuptools<81" dist/*.whl
cd /tmp && PYTHONPATH="$OLDPWD" /tmp/venv/bin/python -m release.smoke_test --expect-version 1.7.0

# The verifier test-suite (proves the gates reject bad packages).
pip install build twine pytest
python -m pytest release/tests -q
```

---

## Rollback & recovery

| Where it failed | What happened | Recovery |
|-----------------|---------------|----------|
| `verify-version` / `build` / `smoke-test` | Nothing reached any index. | Fix the issue. Delete and recreate the tag: `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`, then re-tag. |
| `publish-testpypi` or `verify-testpypi-install` | Package is on **TestPyPI only**; PyPI untouched. | Do **not** approve the `pypi` environment. Delete the bad release on TestPyPI (or just bump and supersede). Fix forward. |
| After `publish-pypi` | Package is **live on PyPI**, which is **immutable** — the same version can never be re-uploaded. | **Yank** the bad release on PyPI (project → Manage → Releases → Yank: hides it from new resolves while keeping pinned installs working), then **fix forward**: `python -m release.bump_version X.Y.(Z+1) --write`, document, tag, release again. |

**Why fix-forward, not delete:** PyPI permanently reserves a deleted version's
filename, so you cannot re-publish `X.Y.Z` after deleting it. Always release a
new version instead.

---

## Notes

- **`setuptools<81` in smoke environments.** `APScheduler==3.6.0` (a pinned
  runtime dependency) imports `pkg_resources`, which setuptools **81+** removed.
  The smoke jobs install `setuptools<81` so the import works; this is an install
  environment detail, not a packaging defect.
- **Smoke runs on Python 3.9.** The runtime deps are pinned to 2021-era versions;
  the lowest supported Python installs them most reliably. The pure
  version/artifact checks run on a current Python (3.11).
- **The version checks track bumps automatically.** Tests and `verify_artifacts`
  read the current version from `scrapydweb/__version__.py`, and the artifact
  resource list is parsed from `MANIFEST.in`, so they stay correct as the project
  evolves.
