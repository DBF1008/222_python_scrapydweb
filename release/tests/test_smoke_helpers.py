# coding: utf-8
"""Tests for the pure release.smoke_test.check_package_data helper.

Exercises the data-presence logic against synthetic package trees without
importing scrapydweb, so it runs anywhere.
"""
import os
import shutil

from release.smoke_test import check_package_data


def _make_pkg(root):
    os.makedirs(os.path.join(root, 'static', 'css'))
    open(os.path.join(root, 'static', 'css', 'a.css'), 'w').close()
    os.makedirs(os.path.join(root, 'templates'))
    open(os.path.join(root, 'templates', 'base.html'), 'w').close()
    os.makedirs(os.path.join(root, 'data', 'parse'))
    open(os.path.join(root, 'data', 'parse', 'ScrapydWeb_demo.log'), 'w').close()
    os.makedirs(os.path.join(root, 'data', 'demo_projects', 'ScrapydWeb_demo'))
    open(os.path.join(root, 'data', 'demo_projects', 'ScrapydWeb_demo', 'scrapy.cfg'), 'w').close()


def test_complete_tree_ok(tmp_path):
    root = str(tmp_path / 'scrapydweb')
    os.makedirs(root)
    _make_pkg(root)
    assert check_package_data(root) == []


def test_missing_templates_detected(tmp_path):
    root = str(tmp_path / 'scrapydweb')
    os.makedirs(root)
    _make_pkg(root)
    shutil.rmtree(os.path.join(root, 'templates'))
    assert any('templates' in m for m in check_package_data(root))


def test_missing_demo_log_detected(tmp_path):
    root = str(tmp_path / 'scrapydweb')
    os.makedirs(root)
    _make_pkg(root)
    os.remove(os.path.join(root, 'data', 'parse', 'ScrapydWeb_demo.log'))
    assert any('ScrapydWeb_demo.log' in m for m in check_package_data(root))


def test_empty_static_dir_detected(tmp_path):
    root = str(tmp_path / 'scrapydweb')
    os.makedirs(root)
    _make_pkg(root)
    os.remove(os.path.join(root, 'static', 'css', 'a.css'))  # leaves an empty dir
    assert any('static' in m for m in check_package_data(root))
