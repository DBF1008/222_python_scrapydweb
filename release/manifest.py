# coding: utf-8
"""Parse ``MANIFEST.in`` into the set of resources a built artifact must carry.

Only the directives ScrapydWeb actually uses (plus a couple of close cousins for
forward-compatibility) are interpreted:

- ``include <path> ...``            -> each path is a required *file*
- ``graft <dir>``                   -> *dir* is required and must contain >=1 file
- ``recursive-include <dir> <pat>`` -> *dir* is required and must contain >=1 file
- ``global-exclude <pattern>``      -> patterns ignored when checking "dir has files"

Deriving the expected resources from MANIFEST.in (rather than hardcoding them)
means the artifact checks stay in sync automatically when MANIFEST.in changes.
"""
import fnmatch
import os

from . import MANIFEST_IN


class ManifestSpec(object):
    """Required files/dirs extracted from a MANIFEST.in."""

    def __init__(self, files, dirs, global_excludes):
        self.files = files                      # list[str], forward-slash, repo-relative
        self.dirs = dirs                        # list[str], forward-slash, repo-relative
        self.global_excludes = global_excludes  # list[str], glob patterns

    def is_excluded(self, path):
        """True if *path*'s basename matches any ``global-exclude`` pattern."""
        name = path.rsplit('/', 1)[-1]
        return any(fnmatch.fnmatch(name, pat) for pat in self.global_excludes)


def _normalize(path):
    return path.replace(os.sep, '/').strip('/')


def parse_manifest(manifest_path=MANIFEST_IN):
    """Read *manifest_path* and return a :class:`ManifestSpec`."""
    files = []
    dirs = []
    global_excludes = []
    with open(manifest_path, encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            directive = parts[0].lower()
            args = parts[1:]
            if directive == 'include':
                files.extend(_normalize(a) for a in args)
            elif directive == 'graft':
                dirs.extend(_normalize(a) for a in args)
            elif directive == 'recursive-include' and args:
                dirs.append(_normalize(args[0]))
            elif directive == 'global-exclude':
                global_excludes.extend(args)
            # other directives (exclude, prune, recursive-exclude, ...) are not
            # used by this project and are intentionally ignored.
    # de-duplicate while preserving order
    files = list(dict.fromkeys(files))
    dirs = list(dict.fromkeys(dirs))
    return ManifestSpec(files, dirs, global_excludes)
