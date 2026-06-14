# coding: utf-8
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope='session')
def built_dist(tmp_path_factory):
    """A directory containing a freshly built sdist + wheel of this repo.

    Honors ``$RELEASE_TEST_DIST`` (point it at an already-built ``dist/`` to skip
    building -- e.g. in CI where the build job already produced artifacts).
    Otherwise builds via ``python -m build``; skips the whole module if the
    ``build`` package is unavailable.
    """
    prebuilt = os.environ.get('RELEASE_TEST_DIST')
    if prebuilt and os.path.isdir(prebuilt):
        if any(n.endswith('.whl') for n in os.listdir(prebuilt)):
            return prebuilt

    try:
        import build  # noqa: F401
    except ImportError:
        pytest.skip("the 'build' package is required to build test artifacts")

    out = str(tmp_path_factory.mktemp('dist'))
    subprocess.run([sys.executable, '-m', 'build', '--outdir', out, REPO_ROOT], check=True)
    return out
