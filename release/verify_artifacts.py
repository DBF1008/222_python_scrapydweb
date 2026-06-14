# coding: utf-8
"""Verify built artifacts in ``dist/`` carry the right version and all resources.

Run after building, before publishing::

    python -m release.verify_artifacts --tag v1.6.0 --dist dist

Inspects the sdist (.tar.gz) and wheel (.whl) with only the standard library and
fails (non-zero, printing every problem) if a required resource from MANIFEST.in
is missing or the embedded version does not match the expected one. This is what
stops a resource-missing or mislabelled package from ever being uploaded.
"""
import argparse
import os
import sys
import tarfile
import zipfile

from . import PACKAGE_NAME, normalize_tag, read_version
from .manifest import parse_manifest


def find_artifacts(dist_dir):
    """Return (sdists, wheels) lists of artifact paths found in *dist_dir*."""
    sdists, wheels = [], []
    for name in sorted(os.listdir(dist_dir)):
        path = os.path.join(dist_dir, name)
        if name.endswith('.tar.gz'):
            sdists.append(path)
        elif name.endswith('.whl'):
            wheels.append(path)
    return sdists, wheels


def _sdist_prefix(members):
    """sdist members live under a single ``name-version/`` top directory."""
    for m in members:
        head = m.split('/', 1)[0]
        if head:
            return head + '/'
    return ''


def _read_metadata_version(text):
    for line in text.splitlines():
        if line.startswith('Version:'):
            return line.split(':', 1)[1].strip()
    return None


def _version_from_filename(filename):
    # scrapydweb-1.6.0.tar.gz  /  scrapydweb-1.6.0-py3-none-any.whl
    base = os.path.basename(filename)
    if base.endswith('.tar.gz'):
        stem = base[:-len('.tar.gz')]
    else:
        stem = base.rsplit('.', 1)[0]
    parts = stem.split('-')
    return parts[1] if len(parts) >= 2 else None


def _dir_has_file(members, prefix, spec):
    for m in members:
        if m.startswith(prefix) and not m.endswith('/') and not spec.is_excluded(m):
            return True
    return False


def _verify_sdist(sdist, expected_version, spec, problems):
    fv = _version_from_filename(sdist)
    if fv != expected_version:
        problems.append("sdist filename version %r != expected %r (%s)"
                        % (fv, expected_version, os.path.basename(sdist)))
    with tarfile.open(sdist, 'r:gz') as tar:
        members = [m.name for m in tar.getmembers()]
        prefix = _sdist_prefix(members)
        relmembers = set(m[len(prefix):] for m in members if m.startswith(prefix))

        if 'PKG-INFO' in relmembers:
            pkg_info = tar.extractfile(prefix + 'PKG-INFO').read().decode('utf-8', 'replace')
            mv = _read_metadata_version(pkg_info)
            if mv != expected_version:
                problems.append("sdist PKG-INFO Version %r != expected %r" % (mv, expected_version))
        else:
            problems.append("sdist is missing PKG-INFO")

        # Baseline files always expected in an sdist.
        for required in ('setup.py', 'README.md', 'scrapydweb/__version__.py'):
            if required not in relmembers:
                problems.append("sdist is missing %s" % required)
        # Every MANIFEST.in include/graft target.
        for f in spec.files:
            if f not in relmembers:
                problems.append("sdist is missing MANIFEST file: %s" % f)
        for d in spec.dirs:
            if not _dir_has_file(relmembers, d + '/', spec):
                problems.append("sdist graft dir has no files: %s" % d)
        # The release tooling must never ship. (tests/ is allowed in the sdist --
        # it is a source archive and the tests never install from it.)
        if any(m.startswith('release/') for m in relmembers):
            problems.append("sdist must not contain the release package "
                            "(release tooling leaked into the build)")


def _verify_wheel(wheel, expected_version, spec, problems):
    fv = _version_from_filename(wheel)
    if fv != expected_version:
        problems.append("wheel filename version %r != expected %r (%s)"
                        % (fv, expected_version, os.path.basename(wheel)))
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())

        meta_candidates = [n for n in names if n.endswith('.dist-info/METADATA')]
        if meta_candidates:
            meta_name = meta_candidates[0]
            distinfo = meta_name[:-len('/METADATA')]
            meta = zf.read(meta_name).decode('utf-8', 'replace')
            mv = _read_metadata_version(meta)
            if mv != expected_version:
                problems.append("wheel METADATA Version %r != expected %r" % (mv, expected_version))
            ep_name = distinfo + '/entry_points.txt'
            if ep_name in names:
                ep = zf.read(ep_name).decode('utf-8', 'replace')
                if 'scrapydweb' not in ep or 'scrapydweb.run:main' not in ep:
                    problems.append("wheel entry_points.txt missing the scrapydweb console script")
            else:
                problems.append("wheel is missing entry_points.txt (console script not registered)")
        else:
            problems.append("wheel is missing *.dist-info/METADATA")

        # Package data: only MANIFEST entries under the package dir live in the wheel.
        if 'scrapydweb/__version__.py' not in names:
            problems.append("wheel is missing scrapydweb/__version__.py")
        for f in spec.files:
            if f.startswith(PACKAGE_NAME + '/') and f not in names:
                problems.append("wheel is missing package data file: %s" % f)
        for d in spec.dirs:
            if d.startswith(PACKAGE_NAME + '/') and not _dir_has_file(names, d + '/', spec):
                problems.append("wheel package data dir has no files: %s" % d)
        # The release tooling and the test suite must never ship to users.
        for forbidden in ('release/', 'tests/'):
            if any(n.startswith(forbidden) for n in names):
                problems.append("wheel must not contain the %s package "
                                "(release tooling/tests leaked into the build)"
                                % forbidden.rstrip('/'))


def verify(dist_dir, expected_version, spec=None):
    """Return a list of problems; an empty list means the artifacts are good."""
    if spec is None:
        spec = parse_manifest()
    problems = []

    sdists, wheels = find_artifacts(dist_dir)
    if len(sdists) != 1:
        problems.append("expected exactly one sdist (*.tar.gz) in %s, found %d"
                        % (dist_dir, len(sdists)))
    if len(wheels) < 1:
        problems.append("expected at least one wheel (*.whl) in %s, found 0" % dist_dir)

    if len(sdists) == 1:
        _verify_sdist(sdists[0], expected_version, spec, problems)
    for wheel in wheels:
        _verify_wheel(wheel, expected_version, spec, problems)

    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify built sdist/wheel content and version.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--tag', help="Git tag, e.g. v1.6.0 (the leading v is stripped)")
    group.add_argument('--expect-version', help="Expected version, e.g. 1.6.0")
    parser.add_argument('--dist', default='dist', help="Directory with built artifacts (default: dist)")
    args = parser.parse_args(argv)

    if args.tag:
        expected = normalize_tag(args.tag)
    elif args.expect_version:
        expected = args.expect_version
    else:
        expected = read_version()

    problems = verify(args.dist, expected)
    if problems:
        print("Artifact verification FAILED for version %s:" % expected)
        for p in problems:
            print("  - %s" % p)
        return 1
    print("Artifact verification PASSED for version %s." % expected)
    return 0


if __name__ == '__main__':
    sys.exit(main())
