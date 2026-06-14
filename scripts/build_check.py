# coding: utf-8
"""Standardized build + smoke-check entry for ScrapydWeb packaging.

This builds the sdist and wheel from the PEP 517/518 configuration, asserts that
both artifacts contain the runtime assets / templates / demo data / metadata, and
finally installs the wheel into a throwaway virtualenv to confirm the console
entry point is registered (without executing it).

Usage:
    python scripts/build_check.py                 # build (prefer `python -m build`) + all checks
    python scripts/build_check.py --backend-direct  # build via setuptools.build_meta (offline, no `build` pkg)
    python scripts/build_check.py --twine-check    # additionally run `twine check`
    python scripts/build_check.py --no-smoke-install  # skip the fresh-venv install check

Exits non-zero if any check fails. Pure standard library; safe to run offline
with --backend-direct.
"""
from __future__ import print_function

import argparse
import configparser
import email
import glob
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from fnmatch import fnmatch


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(REPO_ROOT, "dist")
IS_WINDOWS = os.name == "nt"

# Expected package data members (relative to the package root inside the wheel).
DEMO_DIR = "scrapydweb/data/demo_projects/ScrapydWeb_demo"
DEMO_SETTINGS = DEMO_DIR + "/ScrapydWeb_demo/settings.py"
DEMO_SPIDER = DEMO_DIR + "/ScrapydWeb_demo/spiders/test.py"
DEMO_LOG = "scrapydweb/data/parse/ScrapydWeb_demo.log"
DEMO_CFG = DEMO_DIR + "/scrapy.cfg"
MIN_STATIC_FILES = 27
MIN_TEMPLATE_FILES = 37
EXPECTED_VERSION = "1.6.0"
EXPECTED_ENTRY = "scrapydweb.run:main"


class Reporter(object):
    def __init__(self):
        self.results = []

    def check(self, name, ok, detail=""):
        ok = bool(ok)
        self.results.append((name, ok, detail))
        line = "  [%s] %s" % ("PASS" if ok else "FAIL", name)
        if detail and not ok:
            line += " -- %s" % detail
        print(line)
        return ok

    def all_passed(self):
        return all(ok for _, ok, _ in self.results)

    def summary(self):
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print("\n%d/%d checks passed." % (passed, total))
        if passed != total:
            print("Failed checks:")
            for name, ok, _ in self.results:
                if not ok:
                    print("  - %s" % name)


def run(cmd, **kwargs):
    print("+ %s" % " ".join(cmd))
    return subprocess.run(cmd, **kwargs)


def module_importable(python, module):
    return run(
        [python, "-c", "import %s" % module],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def venv_path(venv_dir, name):
    sub = "Scripts" if IS_WINDOWS else "bin"
    if IS_WINDOWS:
        name += ".exe"
    return os.path.join(venv_dir, sub, name)


def clean():
    for path in (DIST_DIR, os.path.join(REPO_ROOT, "build")):
        if os.path.isdir(path):
            print("Removing %s" % path)
            shutil.rmtree(path, ignore_errors=True)
    for egg in glob.glob(os.path.join(REPO_ROOT, "*.egg-info")):
        print("Removing %s" % egg)
        shutil.rmtree(egg, ignore_errors=True)


def build(python, use_direct, no_isolation, install_build):
    os.makedirs(DIST_DIR, exist_ok=True)

    if not use_direct and not module_importable(python, "build"):
        if install_build:
            run([python, "-m", "pip", "install", "build"], check=True)
        else:
            print("note: 'build' is not installed; falling back to setuptools.build_meta "
                  "(pass --install-build to use `python -m build`).")
            use_direct = True

    if use_direct:
        code = (
            "import setuptools.build_meta as b; "
            "print('built sdist:', b.build_sdist('dist')); "
            "print('built wheel:', b.build_wheel('dist'))"
        )
        cp = run([python, "-c", code], cwd=REPO_ROOT)
    else:
        cmd = [python, "-m", "build", "--outdir", DIST_DIR]
        if no_isolation:
            cmd.append("--no-isolation")
        cp = run(cmd, cwd=REPO_ROOT)

    if cp.returncode != 0:
        raise SystemExit("Build failed (exit %d)." % cp.returncode)


def find_artifact(pattern):
    matches = sorted(glob.glob(os.path.join(DIST_DIR, pattern)))
    return matches[-1] if matches else None


def check_wheel(reporter, wheel_path):
    print("\n== Wheel content check: %s ==" % os.path.basename(wheel_path))
    with zipfile.ZipFile(wheel_path) as z:
        names = z.namelist()
        files = [n for n in names if not n.endswith("/")]

        for member in ("scrapydweb/__init__.py", "scrapydweb/run.py", "scrapydweb/__version__.py"):
            reporter.check("wheel: %s" % member, member in names)

        static_files = [n for n in files if n.startswith("scrapydweb/static/")]
        reporter.check("wheel: static files >= %d (got %d)" % (MIN_STATIC_FILES, len(static_files)),
                       len(static_files) >= MIN_STATIC_FILES)
        reporter.check("wheel: deep static asset present (recursive glob worked)",
                       any("theme-chalk/fonts/" in n for n in static_files))

        template_files = [n for n in files if n.startswith("scrapydweb/templates/")]
        reporter.check("wheel: templates >= %d (got %d)" % (MIN_TEMPLATE_FILES, len(template_files)),
                       len(template_files) >= MIN_TEMPLATE_FILES)

        reporter.check("wheel: demo parse log", DEMO_LOG in names)
        reporter.check("wheel: demo scrapy.cfg", DEMO_CFG in names)
        reporter.check("wheel: demo settings.py (shipped as data)", DEMO_SETTINGS in names)
        reporter.check("wheel: demo spiders/test.py", DEMO_SPIDER in names)

        dist_infos = sorted({n.split("/")[0] for n in names
                             if "/" in n and n.split("/")[0].endswith(".dist-info")})
        reporter.check("wheel: exactly one .dist-info (got %r)" % dist_infos, len(dist_infos) == 1)

        metadata = [n for n in names if fnmatch(n, "*.dist-info/METADATA")]
        if reporter.check("wheel: METADATA present", bool(metadata)):
            headers = email.message_from_string(z.read(metadata[0]).decode("utf-8", "replace"))
            name = (headers.get("Name") or "").strip().lower()
            version = (headers.get("Version") or "").strip()
            reporter.check("wheel: METADATA Name == scrapydweb (got %r)" % name, name == "scrapydweb")
            reporter.check("wheel: METADATA Version == %s (got %r)" % (EXPECTED_VERSION, version),
                           version == EXPECTED_VERSION)

        entry_points = [n for n in names if fnmatch(n, "*.dist-info/entry_points.txt")]
        if reporter.check("wheel: entry_points.txt present", bool(entry_points)):
            parser = configparser.ConfigParser()
            parser.read_string(z.read(entry_points[0]).decode("utf-8"))
            value = parser.get("console_scripts", "scrapydweb", fallback="").replace(" ", "")
            reporter.check("wheel: console entry scrapydweb=%s (got %r)" % (EXPECTED_ENTRY, value),
                           value == EXPECTED_ENTRY)

        reporter.check("wheel: RECORD present", any(fnmatch(n, "*.dist-info/RECORD") for n in names))
        reporter.check("wheel: LICENSE bundled",
                       any(fnmatch(n, "*.dist-info/licenses/LICENSE") or fnmatch(n, "*.dist-info/LICENSE")
                           for n in names))


def check_sdist(reporter, sdist_path):
    print("\n== Sdist content check: %s ==" % os.path.basename(sdist_path))
    with tarfile.open(sdist_path, "r:gz") as t:
        names = t.getnames()

    # Strip the leading "<name>-<version>/" component to compare relative paths.
    rels = set()
    for name in names:
        parts = name.split("/", 1)
        if len(parts) == 2 and parts[1]:
            rels.add(parts[1])

    for member in ("pyproject.toml", "PKG-INFO", "README.md", "README_CN.md",
                   "LICENSE", "HISTORY.md", "scrapydweb/__version__.py",
                   DEMO_LOG, DEMO_CFG, DEMO_SETTINGS, DEMO_SPIDER):
        reporter.check("sdist: %s" % member, member in rels)

    reporter.check("sdist: a static asset present",
                   any(r.startswith("scrapydweb/static/") and "theme-chalk/fonts/" in r for r in rels))
    reporter.check("sdist: a templates file present",
                   any(r.startswith("scrapydweb/templates/") for r in rels))
    reporter.check("sdist: setup.py removed", "setup.py" not in rels)


def twine_check(reporter, python, install_build):
    print("\n== twine check ==")
    if not module_importable(python, "twine") and install_build:
        run([python, "-m", "pip", "install", "twine"], check=False)
    if not module_importable(python, "twine"):
        print("note: twine not available; skipping (pass --install-build to install it).")
        return
    artifacts = sorted(glob.glob(os.path.join(DIST_DIR, "*")))
    cp = run([python, "-m", "twine", "check"] + artifacts)
    reporter.check("twine check passed", cp.returncode == 0)


def smoke_install(reporter, python, wheel_path):
    print("\n== Post-install entry-point check (fresh venv, --no-deps) ==")
    venv_dir = tempfile.mkdtemp(prefix="scrapydweb_smoke_")
    try:
        cp = run([python, "-m", "venv", venv_dir])
        if not reporter.check("smoke: create virtualenv", cp.returncode == 0):
            return

        vpy = venv_path(venv_dir, "python")
        vpip = venv_path(venv_dir, "pip")

        # --no-deps: the pinned runtime deps are not needed to verify the entry
        # point and may not even build on a newer interpreter.
        cp = run([vpip, "install", "--no-deps", wheel_path])
        if not reporter.check("smoke: pip install --no-deps <wheel>", cp.returncode == 0):
            return

        wrapper = venv_path(venv_dir, "scrapydweb")
        reporter.check("smoke: console script installed (%s)" % os.path.basename(wrapper),
                       os.path.exists(wrapper))

        # Resolve the entry point from metadata only -- never import or run it
        # (run.main() creates the app and touches the DB before arg parsing).
        ep_code = (
            "import importlib.metadata as m\n"
            "try:\n"
            "    eps = list(m.entry_points(group='console_scripts'))\n"
            "except TypeError:\n"
            "    eps = list(m.entry_points().get('console_scripts', []))\n"
            "print(next((e.value for e in eps if e.name == 'scrapydweb'), ''))\n"
        )
        cp = run([vpy, "-c", ep_code], capture_output=True, text=True)
        value = (cp.stdout or "").strip()
        reporter.check("smoke: entry point resolves to %s (got %r)" % (EXPECTED_ENTRY, value),
                       value == EXPECTED_ENTRY)

        files_code = (
            "import importlib.metadata as m\n"
            "fs = [str(f) for f in (m.files('scrapydweb') or [])]\n"
            "print(sum(1 for n in fs if n.startswith('scrapydweb/static/')))\n"
            "print('YES' if %r in fs else 'NO')\n" % DEMO_SETTINGS
        )
        cp = run([vpy, "-c", files_code], capture_output=True, text=True)
        out = (cp.stdout or "").strip().splitlines()
        static_count = int(out[0]) if out and out[0].isdigit() else 0
        has_settings = len(out) > 1 and out[1] == "YES"
        reporter.check("smoke: installed static files >= %d (got %d)" % (MIN_STATIC_FILES, static_count),
                       static_count >= MIN_STATIC_FILES)
        reporter.check("smoke: installed demo settings.py present", has_settings)
    finally:
        shutil.rmtree(venv_dir, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build ScrapydWeb's sdist+wheel and verify their contents and installability.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--python", default=sys.executable,
                        help="Interpreter used to build and to create the smoke venv (default: this one).")
    parser.add_argument("--backend-direct", action="store_true",
                        help="Build via setuptools.build_meta directly (offline, no `build` package).")
    parser.add_argument("--no-isolation", action="store_true",
                        help="Pass --no-isolation to `python -m build` (offline-friendly).")
    parser.add_argument("--install-build", action="store_true",
                        help="pip install `build` (and `twine` if --twine-check) when missing.")
    parser.add_argument("--twine-check", action="store_true", help="Also run `twine check dist/*`.")
    parser.add_argument("--no-smoke-install", action="store_true",
                        help="Skip the fresh-venv post-install entry-point check.")
    parser.add_argument("--keep-dist", action="store_true", help="Do not clean dist/ and build/ first.")
    args = parser.parse_args(argv)

    print("Repository root: %s" % REPO_ROOT)
    print("Build interpreter: %s" % args.python)

    if not args.keep_dist:
        print("\n== Clean ==")
        clean()

    print("\n== Build sdist + wheel ==")
    build(args.python, args.backend_direct, args.no_isolation, args.install_build)

    reporter = Reporter()

    wheel_path = find_artifact("*.whl")
    sdist_path = find_artifact("*.tar.gz")
    reporter.check("artifact: wheel produced", wheel_path is not None)
    reporter.check("artifact: sdist produced", sdist_path is not None)

    if wheel_path:
        check_wheel(reporter, wheel_path)
    if sdist_path:
        check_sdist(reporter, sdist_path)
    if args.twine_check:
        twine_check(reporter, args.python, args.install_build)
    if wheel_path and not args.no_smoke_install:
        smoke_install(reporter, args.python, wheel_path)

    print("\n== Summary ==")
    reporter.summary()
    return 0 if reporter.all_passed() else 1


if __name__ == "__main__":
    sys.exit(main())
