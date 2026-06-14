# coding: utf-8
"""Assert the Git tag agrees with every place ScrapydWeb records its version.

Run as a CLI in the release pipeline *before* building::

    python -m release.check_version --tag v1.6.0

Exits non-zero (printing every problem found) if anything is inconsistent, so a
mistagged or under-documented release never reaches the build stage.
"""
import argparse
import re
import sys

from . import (HISTORY_MD, README_MD, SETUP_PY, VERSION_FILE, VERSION_RE,
               normalize_tag, read_version)

# The README must keep the *dynamic* PyPI badge (it renders the live version),
# never a hardcoded version, so it can never go stale.
_README_DYNAMIC_BADGE_RE = re.compile(r'img\.shields\.io/pypi/v/scrapydweb\.svg')
# A hardcoded version baked into a shields pypi badge path, e.g. /pypi/v/scrapydweb/1.5.0
_README_PINNED_BADGE_RE = re.compile(r'img\.shields\.io/pypi/v/scrapydweb/\d')


def _history_versions(history_text):
    """Return release versions in document order from HISTORY.md.

    Entries look like ``1.6.0 (2025-02-16)`` or ``[1.3.0](url) (2019-08-04)``.
    """
    return re.findall(r'^\[?(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)', history_text, re.M)


def check_version(tag, version_file=VERSION_FILE, setup_py=SETUP_PY,
                  history_md=HISTORY_MD, readme_md=README_MD):
    """Return a list of human-readable problems; an empty list means consistent."""
    problems = []

    version = read_version(version_file)
    if not VERSION_RE.match(version):
        problems.append("__version__ %r is not a valid version string" % version)

    # 1) Git tag <-> source of truth
    if tag is not None:
        tag_version = normalize_tag(tag)
        if tag_version != version:
            problems.append(
                "Git tag %r (-> %r) does not match scrapydweb/__version__.py %r"
                % (tag, tag_version, version))

    # 2) setup.py must still derive the version from __version__.py, not hardcode it
    with open(setup_py, encoding='utf-8') as f:
        setup_text = f.read()
    if "about['__version__']" not in setup_text and 'about["__version__"]' not in setup_text:
        problems.append(
            "setup.py no longer reads version from __version__.py "
            "(expected version=about['__version__'])")
    if re.search(r"""version\s*=\s*['"]\d+\.\d+""", setup_text):
        problems.append("setup.py appears to hardcode a version literal")

    # 3) HISTORY.md must document this release as the newest entry
    with open(history_md, encoding='utf-8') as f:
        history_text = f.read()
    versions = _history_versions(history_text)
    if version not in versions:
        problems.append("HISTORY.md has no entry for version %s" % version)
    elif versions[0] != version:
        problems.append(
            "HISTORY.md newest entry is %s, expected the released version %s on top"
            % (versions[0], version))

    # 4) README PyPI badge must stay dynamic
    with open(readme_md, encoding='utf-8') as f:
        readme_text = f.read()
    if _README_PINNED_BADGE_RE.search(readme_text):
        problems.append("README PyPI version badge is hardcoded to a version; keep it dynamic")
    elif not _README_DYNAMIC_BADGE_RE.search(readme_text):
        problems.append(
            "README is missing the dynamic PyPI version badge (shields.io/pypi/v/scrapydweb.svg)")

    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check version consistency across the repo.")
    parser.add_argument('--tag', help="Git tag to validate, e.g. v1.6.0 (omit to only cross-check files)")
    args = parser.parse_args(argv)

    problems = check_version(args.tag)
    version = read_version()
    if problems:
        print("Version consistency check FAILED for version %s:" % version)
        for p in problems:
            print("  - %s" % p)
        return 1
    target = normalize_tag(args.tag) if args.tag else version
    print("Version consistency check PASSED (version %s)." % target)
    return 0


if __name__ == '__main__':
    sys.exit(main())
