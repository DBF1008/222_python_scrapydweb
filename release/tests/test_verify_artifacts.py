# coding: utf-8
"""Tests for release.verify_artifacts against real built artifacts.

The good build must pass; deliberately *tampered* artifacts (a resource removed,
or a version-mismatched filename) must be rejected. These cases are the core
guarantee that the release flow won't ship a resource-missing or mislabelled
package.
"""
import os
import shutil
import tarfile
import zipfile

from release import read_version
from release.verify_artifacts import verify

EXPECTED = read_version()  # current source-of-truth version, so tests track bumps


def _artifacts(dist):
    sdist = next(os.path.join(dist, n) for n in os.listdir(dist) if n.endswith('.tar.gz'))
    wheel = next(os.path.join(dist, n) for n in os.listdir(dist) if n.endswith('.whl'))
    return sdist, wheel


def _repack_tar(src, dst, drop):
    with tarfile.open(src, 'r:gz') as tin, tarfile.open(dst, 'w:gz') as tout:
        for m in tin.getmembers():
            if drop(m.name):
                continue
            tout.addfile(m, tin.extractfile(m) if m.isfile() else None)


def _repack_zip(src, dst, drop):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if drop(item.filename):
                continue
            zout.writestr(item, zin.read(item.filename))


def _dist_dir(tmp_path, sdist, wheel):
    """Assemble a dist directory from given sdist/wheel paths."""
    out = tmp_path / 'dist'
    out.mkdir()
    shutil.copy(sdist, out / os.path.basename(sdist))
    shutil.copy(wheel, out / os.path.basename(wheel))
    return str(out)


def test_good_build_passes(built_dist):
    assert verify(built_dist, EXPECTED) == []


def test_version_mismatch_fails(built_dist):
    # Correct artifacts, wrong expected version -> every version check trips.
    problems = verify(built_dist, '9.9.9')
    assert any('!= expected' in p for p in problems)


def test_missing_templates_in_wheel_fails(tmp_path, built_dist):
    sdist, wheel = _artifacts(built_dist)
    tampered_wheel = str(tmp_path / os.path.basename(wheel))
    _repack_zip(wheel, tampered_wheel, drop=lambda n: n.startswith('scrapydweb/templates/'))
    dist = _dist_dir(tmp_path, sdist, tampered_wheel)
    problems = verify(dist, EXPECTED)
    assert any('templates' in p for p in problems), problems


def test_missing_demo_log_in_sdist_fails(tmp_path, built_dist):
    sdist, wheel = _artifacts(built_dist)
    tampered_sdist = str(tmp_path / os.path.basename(sdist))
    _repack_tar(sdist, tampered_sdist,
                drop=lambda n: n.endswith('scrapydweb/data/parse/ScrapydWeb_demo.log'))
    dist = _dist_dir(tmp_path, tampered_sdist, wheel)
    problems = verify(dist, EXPECTED)
    assert any('ScrapydWeb_demo.log' in p for p in problems), problems


def test_missing_static_in_wheel_fails(tmp_path, built_dist):
    sdist, wheel = _artifacts(built_dist)
    tampered_wheel = str(tmp_path / os.path.basename(wheel))
    _repack_zip(wheel, tampered_wheel, drop=lambda n: n.startswith('scrapydweb/static/'))
    dist = _dist_dir(tmp_path, sdist, tampered_wheel)
    problems = verify(dist, EXPECTED)
    assert any('static' in p for p in problems), problems


def test_filename_version_mismatch_fails(tmp_path, built_dist):
    # Rename the wheel to a different version while its METADATA stays correct;
    # the filename-version guard must still trip.
    sdist, wheel = _artifacts(built_dist)
    bad_name = os.path.basename(wheel).replace('-%s-' % EXPECTED, '-9.9.9-')
    assert bad_name != os.path.basename(wheel)
    out = tmp_path / 'dist'
    out.mkdir()
    shutil.copy(sdist, out / os.path.basename(sdist))
    shutil.copy(wheel, out / bad_name)
    problems = verify(str(out), EXPECTED)
    assert any('wheel filename version' in p for p in problems), problems


def test_missing_sdist_fails(tmp_path, built_dist):
    _sdist, wheel = _artifacts(built_dist)
    out = tmp_path / 'dist'
    out.mkdir()
    shutil.copy(wheel, out / os.path.basename(wheel))  # wheel only, no sdist
    problems = verify(str(out), EXPECTED)
    assert any('exactly one sdist' in p for p in problems), problems


def test_release_tooling_not_in_artifacts(built_dist):
    # The release/ tooling must never be packaged; tests/ must not be in the
    # installable wheel (it may remain in the source sdist).
    sdist, wheel = _artifacts(built_dist)
    with zipfile.ZipFile(wheel) as z:
        assert not any(n.startswith('release/') for n in z.namelist())
        assert not any(n.startswith('tests/') for n in z.namelist())
    with tarfile.open(sdist) as t:
        assert not any('/release/' in n for n in t.getnames())


def test_leaked_release_package_in_wheel_fails(tmp_path, built_dist):
    # Inject a release/ package into the wheel and confirm the guard rejects it.
    sdist, wheel = _artifacts(built_dist)
    tampered = str(tmp_path / os.path.basename(wheel))
    with zipfile.ZipFile(wheel) as zin, \
            zipfile.ZipFile(tampered, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr('release/__init__.py', b'# leaked\n')
    dist = _dist_dir(tmp_path, sdist, tampered)
    problems = verify(dist, EXPECTED)
    assert any('must not contain' in p and 'release' in p for p in problems), problems
