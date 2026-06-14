# coding: utf-8
"""Isolated tests for the release tooling.

Kept in their own package (not under ``tests/``) because ``tests/conftest.py``
imports the full Flask app at collection time and needs a running Scrapyd. These
tests only need the standard library plus ``build`` and run independently::

    python -m pytest release/tests -q
"""
