# coding: utf-8
# ──────────────────────────────────────────────────────────
# Minimal setup.py shim for PEP 517 builds.
# ──────────────────────────────────────────────────────────
# All static metadata (dependencies, entry points,
# classifiers, etc.) lives in pyproject.toml.
#
# This shim provides two dynamic fields that cannot be
# expressed declaratively:
#   1. version  — read from scrapydweb/__version__.py
#   2. readme   — README.md with GitHub emoji shortcodes
#                 (:word:) stripped for correct PyPI rendering
# ──────────────────────────────────────────────────────────
import io
import os
import re

from setuptools import setup

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

about = {}
with open(os.path.join(CURRENT_DIR, "scrapydweb", "__version__.py")) as f:
    exec(f.read(), about)

with io.open("README.md", "r", encoding="utf-8") as f:
    long_description = re.sub(r":\w+:\s", "", f.read())

setup(
    version=about["__version__"],
    long_description=long_description,
    long_description_content_type="text/markdown",
)
