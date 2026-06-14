# coding: utf-8
"""Bump the single source-of-truth version and keep HISTORY.md in sync.

    python -m release.bump_version 1.7.0            # dry run: show planned edits
    python -m release.bump_version 1.7.0 --write    # apply the edits

Updates ``scrapydweb/__version__.py`` (which setup.py reads) and inserts a dated
skeleton entry at the top of HISTORY.md, then prints the git tag command. Doing
both in one step is what keeps a release's version, changelog, and tag in
agreement -- exactly what :mod:`release.check_version` later enforces.
"""
import argparse
import datetime
import re
import sys

from . import HISTORY_MD, VERSION_FILE, VERSION_RE, read_version


def _version_key(version):
    """Sort key so pre-releases order *before* the matching final release."""
    m = re.match(r'^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$', version)
    if not m:
        raise ValueError("cannot parse version %r" % version)
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if m.group(4) is None:
        pre_rank, pre_num = 3, 0          # final release sorts after a/b/rc
    else:
        pre_rank = {'a': 0, 'b': 1, 'rc': 2}[m.group(4)]
        pre_num = int(m.group(5))
    return (major, minor, patch, pre_rank, pre_num)


def bump(new_version, write=False, date=None, version_file=VERSION_FILE, history_md=HISTORY_MD):
    """Return a list of human-readable actions; apply them when *write* is True."""
    if not VERSION_RE.match(new_version):
        raise SystemExit("Invalid version %r (expected X.Y.Z or X.Y.ZrcN)" % new_version)
    current = read_version(version_file)
    if _version_key(new_version) <= _version_key(current):
        raise SystemExit("New version %s must be greater than current %s" % (new_version, current))

    date = date or datetime.date.today().isoformat()
    actions = []

    with open(version_file, encoding='utf-8') as f:
        vtext = f.read()
    new_vtext = re.sub(r"(__version__\s*=\s*['\"])[^'\"]+(['\"])",
                       r"\g<1>%s\g<2>" % new_version, vtext, count=1)
    actions.append("set __version__ = %s in %s" % (new_version, version_file))

    with open(history_md, encoding='utf-8') as f:
        htext = f.read()
    entry = "%s (%s)\n%s\n- TODO: summarise changes\n\n\n" % (new_version, date, '-' * 18)
    # Insert immediately after the "Release History\n===============" header.
    # Find with a regex (underline length is flexible) but splice with plain
    # slicing to avoid re.sub replacement-string escaping pitfalls.
    header_match = re.search(r"Release History\n=+\n", htext)
    if header_match:
        idx = header_match.end()
        new_htext = htext[:idx] + entry + htext[idx:]
    else:
        new_htext = entry + htext
    actions.append("insert HISTORY.md entry: %s (%s)" % (new_version, date))

    if write:
        with open(version_file, 'w', encoding='utf-8') as f:
            f.write(new_vtext)
        with open(history_md, 'w', encoding='utf-8') as f:
            f.write(new_htext)

    actions.append("next: git commit -am 'Release %s' && git tag v%s && git push --follow-tags"
                   % (new_version, new_version))
    return actions


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bump the source-of-truth version.")
    parser.add_argument('version', help="New version, e.g. 1.7.0")
    parser.add_argument('--write', action='store_true', help="Apply edits (otherwise dry run)")
    parser.add_argument('--date', help="Override the HISTORY.md date (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    actions = bump(args.version, write=args.write, date=args.date)
    prefix = "Applied" if args.write else "[dry run] would"
    for a in actions:
        print("%s: %s" % (prefix, a))
    if not args.write:
        print("Re-run with --write to apply.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
