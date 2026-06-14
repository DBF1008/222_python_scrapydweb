# coding: utf-8
"""Tag-driven release tooling for ScrapydWeb.

This package holds *standalone* verification helpers used by the release
pipeline (``.github/workflows/release.yml``). They depend only on the Python
standard library, so they run in any environment (CI runners, a clean venv, or
the maintainer's machine) without pulling in scrapydweb's runtime dependencies.

Modules
-------
- :mod:`release.manifest`         parse ``MANIFEST.in`` into the resources an artifact must contain
- :mod:`release.check_version`    assert the Git tag and every place that records the version agree
- :mod:`release.verify_artifacts` assert the built sdist/wheel carry the right version and resources
- :mod:`release.smoke_test`       assert an *installed* package imports, exposes its CLI, ships its data
- :mod:`release.bump_version`     bump the single source-of-truth version and keep HISTORY.md in sync
"""
import os
import re

# Repo root = the parent of this package directory.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PACKAGE_NAME = 'scrapydweb'

# The single source of truth for the version; setup.py exec()s this file.
VERSION_FILE = os.path.join(ROOT_DIR, 'scrapydweb', '__version__.py')
SETUP_PY = os.path.join(ROOT_DIR, 'setup.py')
HISTORY_MD = os.path.join(ROOT_DIR, 'HISTORY.md')
README_MD = os.path.join(ROOT_DIR, 'README.md')
MANIFEST_IN = os.path.join(ROOT_DIR, 'MANIFEST.in')

# Accept final releases (1.6.0) and the PEP 440 pre-releases this project has
# used historically (e.g. 1.0.0rc1). Kept deliberately small.
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$')

_VERSION_ASSIGN_RE = re.compile(r"""^__version__\s*=\s*['"]([^'"]+)['"]""", re.M)


def read_version(version_file=VERSION_FILE):
    """Return ``__version__`` from *version_file* without importing the package.

    Parsing (instead of ``exec``) keeps this dependency-free and lets tests
    point at a temporary copy of the file.
    """
    with open(version_file, encoding='utf-8') as f:
        text = f.read()
    match = _VERSION_ASSIGN_RE.search(text)
    if not match:
        raise ValueError("Could not find __version__ assignment in %s" % version_file)
    return match.group(1)


def normalize_tag(tag):
    """Strip a leading ``v`` from a Git tag, e.g. ``v1.6.0`` -> ``1.6.0``."""
    return tag[1:] if tag and tag[0] in ('v', 'V') else tag
