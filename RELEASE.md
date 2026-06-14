# Release Process

This document describes how to publish a new release of **ScrapydWeb**.
The release pipeline is automated via GitHub Actions and enforces version
consistency, artifact validation, and smoke testing before any upload.

## Prerequisites

### Local tooling

```bash
pip install build twine
```

### GitHub repository secrets

The following secrets **must** be configured under
*Settings → Secrets and variables → Actions* before the first release:

| Secret | Used By | Where to generate |
|--------|---------|-------------------|
| `TEST_PYPI_API_TOKEN` | `publish-testpypi` job | [test.pypi.org → Account Settings → API tokens](https://test.pypi.org/manage/account/token/) |
| `PYPI_API_TOKEN` | `publish-pypi` job | [pypi.org → Account Settings → API tokens](https://pypi.org/manage/account/token/) |

> **Tip:** Scope each token to the `scrapydweb` project only — never grant
> organisation-wide or global tokens.

---

## Creating a Release

### Step 1 — Bump the version

Edit **exactly two files**:

1. `scrapydweb/__version__.py` — update `__version__` to the new version
   (e.g. `'1.7.0'`).
2. `HISTORY.md` — add a new section at the top with the version and today's
   date, e.g.:

   ```
   1.7.0 (2026-06-14)
   ------------------
   - Description of changes
   ```

Commit and push to the default branch:

```bash
git add scrapydweb/__version__.py HISTORY.md
git commit -m "Bump version to 1.7.0"
git push origin main
```

### Step 2 — Run local pre-flight checks

```bash
make release
```

This runs the full validation pipeline locally:

- **check-version** — confirms `__version__.py`, `HISTORY.md`, and `setup.py`
  all report the same version.
- **build** — produces `dist/scrapydweb-1.7.0.tar.gz` and
  `dist/scrapydweb-1.7.0-py3-none-any.whl`.
- **validate** — runs `twine check` and verifies that required files
  (`__version__.py`, `__init__.py`, `run.py`, `setup.py`, `README.md`,
  `HISTORY.md`, `requirements.txt`, `MANIFEST.in`) are present in the sdist,
  and that the wheel contains the core modules.
- **smoke-test** — installs the wheel in a throwaway virtual environment,
  verifies `import scrapydweb`, checks that `scrapydweb.__version__` matches,
  and exercises the CLI entry point (`scrapydweb --help`).

If any step fails, fix the issue before proceeding.

### Step 3 — Tag and push

```bash
git tag v1.7.0
git push origin v1.7.0
```

Pushing the tag triggers the GitHub Actions release pipeline automatically:

1. **validate** — re-checks version consistency at the tagged commit.
2. **build** — produces fresh sdist and wheel artifacts.
3. **smoke-test** — installs and tests both wheel and sdist in isolated venvs.
4. **publish-testpypi** — uploads to [TestPyPI](https://test.pypi.org) and
   verifies the uploaded package installs correctly.

> The pipeline **will not upload to PyPI** automatically. PyPI promotion
> requires an explicit manual step (see Step 5).

### Step 4 — Verify on TestPyPI

Wait for the Actions run to go green, then verify locally:

```bash
pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  scrapydweb==1.7.0
```

> `--extra-index-url` is required because dependencies (Flask, SQLAlchemy,
> etc.) live on the real PyPI, not TestPyPI.

Run a quick sanity check:

```bash
python -c "import scrapydweb; print(scrapydweb.__version__)"
scrapydweb --help
```

### Step 5 — Promote to PyPI

Once you are satisfied with the TestPyPI build:

1. Go to the repository's **Actions** tab on GitHub.
2. Select the **Release Pipeline** workflow.
3. Click **Run workflow**.
4. Enter the tag name (e.g. `v1.7.0`).
5. Leave **Dry run** unchecked (checked = upload to TestPyPI again).
6. Click **Run workflow**.

The workflow will:

1. Check out the tagged commit.
2. Re-run all validation, build, and smoke-test steps.
3. Upload to **PyPI** using `PYPI_API_TOKEN`.
4. Verify the published package installs correctly from PyPI.

---

## Rollback Procedures

### Before PyPI publish (only on TestPyPI)

If something is wrong after the tag push but **before** promoting to PyPI:

```bash
# Delete the remote tag
git push origin :refs/tags/v1.7.0

# Delete the local tag
git tag -d v1.7.0
```

Optionally yank the broken release from TestPyPI via the
[TestPyPI web UI](https://test.pypi.org/manage/project/scrapydweb/releases/).

### After PyPI publish

Once a version is published to PyPI it **cannot be deleted or overwritten**.

1. **Yank the release** (hides it from `pip install` but keeps the version
   reserved):

   ```bash
   twine yank scrapydweb 1.7.0
   ```

   Or use the [PyPI web UI](https://pypi.org/manage/project/scrapydweb/releases/).

2. **Fix the issue**, bump to the **next patch version** (e.g. `1.7.1`),
   and go through the release process again.

> **⚠️  NEVER re-use a version number that was published to PyPI**, even if
> the release was yanked. PyPI reserves all previously-used version numbers.

---

## Failure Scenarios

| Failure Point | What Happens | How to Recover |
|---|---|---|
| **validate** fails | Pipeline stops; no artifacts produced. | Fix version/HISTORY mismatch, amend commit, delete + recreate tag. |
| **build** fails | Pipeline stops; nothing uploaded. | Fix packaging issue, bump version, re-release. |
| **smoke-test** fails | Pipeline stops; nothing uploaded. | Debug install failure, bump patch, re-release. |
| **publish-testpypi** fails | May have partially uploaded. | Check TestPyPI; yank partial upload if needed; fix token or network issue; retry. |
| **publish-pypi** fails | May have partially uploaded. | Yank via `twine yank` or PyPI UI; fix issue; bump patch version; re-promote. |
| **Post-upload verify** fails | Package IS published. | **Do not delete.** Yank if broken, bump patch, re-release. |

---

## Troubleshooting

### "Version mismatch" error

All three sources must agree exactly:

```bash
python -c "exec(open('scrapydweb/__version__.py').read()); print(__version__)"
grep -m1 '(' HISTORY.md
python setup.py --version
```

If any of these differ, update `__version__.py` and `HISTORY.md`, commit,
and re-tag.

### Smoke test fails with `ModuleNotFoundError`

A new dependency was likely added to `setup.py` without being tested.
Install the package locally and check which import fails:

```bash
pip install -e .
python -c "import scrapydweb"
```

### TestPyPI upload fails with `403 Forbidden`

The `TEST_PYPI_API_TOKEN` secret may be expired or lack project scope.
Regenerate at [test.pypi.org → Account Settings → API tokens](https://test.pypi.org/manage/account/token/).

### PyPI upload fails with `403 Forbidden`

Same as above — regenerate `PYPI_API_TOKEN` at
[pypi.org → Account Settings → API tokens](https://pypi.org/manage/account/token/).

### GitHub Actions "Run workflow" button is greyed out

The `publish-pypi` job is defined on the default branch. Make sure the
workflow file (`.github/workflows/release.yml`) exists on the default branch
before trying to trigger a manual run.
