# coding: utf-8
"""Tests for release.check_version using synthetic temp files.

Each case writes a minimal version/setup/history/readme set and asserts the
checker passes when consistent and fails (with a useful message) otherwise.
"""
from release.check_version import check_version

GOOD_VERSION = "# coding: utf-8\n__version__ = '1.6.0'\n"
GOOD_SETUP = "setup(\n    name='scrapydweb',\n    version=about['__version__'],\n)\n"
GOOD_HISTORY = (
    "Release History\n===============\n"
    "1.6.0 (2025-02-16)\n------------------\n- thing\n\n\n"
    "1.5.0 (2024-02-11)\n------------------\n- old\n"
)
GOOD_README = (
    "[![PyPI - scrapydweb Version]"
    "(https://img.shields.io/pypi/v/scrapydweb.svg)]"
    "(https://pypi.org/project/scrapydweb/)\n"
)


def _files(tmp_path, version=GOOD_VERSION, setup=GOOD_SETUP,
           history=GOOD_HISTORY, readme=GOOD_README):
    vf = tmp_path / '__version__.py'
    vf.write_text(version, encoding='utf-8')
    sp = tmp_path / 'setup.py'
    sp.write_text(setup, encoding='utf-8')
    hm = tmp_path / 'HISTORY.md'
    hm.write_text(history, encoding='utf-8')
    rm = tmp_path / 'README.md'
    rm.write_text(readme, encoding='utf-8')
    return dict(version_file=str(vf), setup_py=str(sp),
                history_md=str(hm), readme_md=str(rm))


def test_passes_when_consistent(tmp_path):
    assert check_version('v1.6.0', **_files(tmp_path)) == []


def test_passes_without_tag(tmp_path):
    # No tag -> only the cross-file checks run; still consistent.
    assert check_version(None, **_files(tmp_path)) == []


def test_tag_mismatch_fails(tmp_path):
    problems = check_version('v9.9.9', **_files(tmp_path))
    assert any('does not match' in p for p in problems)


def test_invalid_version_fails(tmp_path):
    problems = check_version('vnot.a.version', **_files(tmp_path, version="__version__ = 'not.a.version'\n"))
    assert any('not a valid version' in p for p in problems)


def test_missing_history_entry_fails(tmp_path):
    history = "Release History\n===============\n1.5.0 (2024-02-11)\n------------------\n- old\n"
    problems = check_version('v1.6.0', **_files(tmp_path, history=history))
    assert any('HISTORY.md has no entry' in p for p in problems)


def test_history_not_on_top_fails(tmp_path):
    history = (
        "Release History\n===============\n"
        "1.5.0 (2024-02-11)\n------------------\n- old\n\n\n"
        "1.6.0 (2025-02-16)\n------------------\n- thing\n"
    )
    problems = check_version('v1.6.0', **_files(tmp_path, history=history))
    assert any('newest entry' in p for p in problems)


def test_hardcoded_readme_badge_fails(tmp_path):
    readme = "[![PyPI](https://img.shields.io/pypi/v/scrapydweb/1.5.0.svg)](x)\n"
    problems = check_version('v1.6.0', **_files(tmp_path, readme=readme))
    assert any('hardcoded' in p for p in problems)


def test_missing_readme_badge_fails(tmp_path):
    readme = "# scrapydweb\nno badge here\n"
    problems = check_version('v1.6.0', **_files(tmp_path, readme=readme))
    assert any('dynamic PyPI version badge' in p for p in problems)


def test_hardcoded_setup_version_fails(tmp_path):
    setup = "setup(\n    name='scrapydweb',\n    version='1.6.0',\n)\n"
    problems = check_version('v1.6.0', **_files(tmp_path, setup=setup))
    # Hardcoding both drops the about[...] read and matches the literal-version guard.
    assert any('hardcode' in p for p in problems)
    assert any('no longer reads version' in p for p in problems)
