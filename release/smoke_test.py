# coding: utf-8
"""Smoke-test an *installed* scrapydweb (run inside a clean venv).

    python -m release.smoke_test --expect-version 1.6.0

Confirms the installed/published package (a) imports, (b) reports the expected
version, (c) registered the ``scrapydweb`` console entry point, and (d) shipped
its packaged data (static/templates/demo files). By importing rather than
building, it catches packaging gaps that only surface after installation.
"""
import argparse
import os
import sys

# Concrete package-data files/dirs that must resolve next to the installed
# package. Mirrors MANIFEST.in; kept explicit so this module needs no repo
# checkout to run inside the install environment.
REQUIRED_DIRS = ('static', 'templates')
REQUIRED_FILES = (
    os.path.join('data', 'parse', 'ScrapydWeb_demo.log'),
    os.path.join('data', 'demo_projects', 'ScrapydWeb_demo', 'scrapy.cfg'),
)


def check_package_data(pkg_root):
    """Return a list of missing required data paths under *pkg_root*.

    Pure function (imports no scrapydweb) so it is unit-testable against a
    synthetic directory tree.
    """
    missing = []
    for d in REQUIRED_DIRS:
        full = os.path.join(pkg_root, d)
        has_file = os.path.isdir(full) and any(
            files for _root, _dirs, files in os.walk(full))
        if not has_file:
            missing.append(d + '/ (non-empty dir)')
    for f in REQUIRED_FILES:
        if not os.path.isfile(os.path.join(pkg_root, f)):
            missing.append(f)
    return missing


def _entry_point_registered():
    try:
        from importlib import metadata as importlib_metadata
    except ImportError:  # pragma: no cover - py<3.8 fallback
        import importlib_metadata  # type: ignore
    try:
        eps = importlib_metadata.entry_points()
    except Exception:
        return False
    # The entry_points() return type differs across Python versions.
    try:
        console = eps.select(group='console_scripts')
    except AttributeError:
        console = eps.get('console_scripts', [])
    return any(ep.name == 'scrapydweb' for ep in console)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Smoke-test an installed scrapydweb.")
    parser.add_argument('--expect-version', required=True, help="Version the install must report")
    args = parser.parse_args(argv)

    problems = []

    try:
        import scrapydweb
    except Exception as err:  # noqa: BLE001 - any import failure is a smoke-test failure
        print("Smoke test FAILED: cannot import scrapydweb: %r" % err)
        return 1

    actual = getattr(scrapydweb, '__version__', None)
    if actual != args.expect_version:
        problems.append("imported scrapydweb.__version__ %r != expected %r"
                        % (actual, args.expect_version))

    pkg_root = os.path.dirname(os.path.abspath(scrapydweb.__file__))
    for m in check_package_data(pkg_root):
        problems.append("missing packaged data: %s" % m)

    if not _entry_point_registered():
        problems.append("console entry point 'scrapydweb' is not registered")

    if problems:
        print("Smoke test FAILED for version %s:" % args.expect_version)
        for p in problems:
            print("  - %s" % p)
        return 1
    print("Smoke test PASSED: scrapydweb %s imported, data present, CLI registered." % actual)
    return 0


if __name__ == '__main__':
    sys.exit(main())
