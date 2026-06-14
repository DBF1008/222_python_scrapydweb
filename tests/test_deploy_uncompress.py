# coding: utf-8
"""Regression tests for uncompressing project archives and locating scrapy.cfg.

These cover the Windows/CN compatibility gap in the Python 3 branch of
``DeployUploadView.uncompress_to_tmpdir`` / ``search_scrapy_cfg_path``:

* zip files packaged on Windows (cp936/gbk) or macOS (UTF-8 without the EFS flag)
  used to extract into mojibake folder names via ``zipfile.extractall``;
* a member flagged UTF-8 but carrying invalid bytes, or an undecodable on-disk
  name, could leave the search with surrogate / unusable paths or no scrapy.cfg;
* a nested project directory must still resolve to a valid project root.

The tests exercise the pure helpers directly so they need neither a running
Scrapyd server nor a Flask request context.
"""
import io
import os
import tempfile
import zipfile

import pytest

from scrapydweb.views.operations.deploy import (
    ZIP_UTF8_FLAG,
    decode_zip_member_filename,
    extract_zip_to_dir,
    normalize_pathname,
    walk_for_scrapy_cfg,
)


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ZIP = os.path.join(ROOT_DIR, 'data.zip')

SCRAPY_CFG_CONTENT = (
    u'[settings]\ndefault = demo.settings\n\n[deploy]\nproject = demo\n'
)

# Archives shipped inside tests/data.zip. The cp936/utf8-without-flag ones used
# to extract into mojibake folder names under Python 3.
CN_ZIPS = [
    u'demo - 副本 - Win7CN.zip',           # Windows 7 CN, cp936 bytes
    u'demo - 副本 - Win10cp936.zip',       # Windows 10 CN, cp936 bytes
    u'demo - 副本 - Win7CNsendzipped.zip',  # Win "send to compressed"
    u'demo - 副本 - macOS.zip',            # macOS, UTF-8 without EFS flag
    u'副本.zip',                            # project root itself is CN
]
ASCII_ZIPS = [
    'demo - Win7CNsendzipped.zip',
    'demo - Win10cp1252.zip',
    'demo - Ubuntu.zip',
]


def _extract_fixture(name, dest_dir):
    """Extract a single archive from tests/data.zip and return its path."""
    arcname = 'data/%s' % name
    with zipfile.ZipFile(DATA_ZIP) as big:
        big.extract(arcname, dest_dir)
    return os.path.join(dest_dir, 'data', name)


@pytest.fixture
def fixture_extractor(tmp_path):
    dest = str(tmp_path / 'archives')
    return lambda name: _extract_fixture(name, dest)


def _uncompress(archive_path):
    """Mimic the PY3 branch of uncompress_to_tmpdir without app/request state."""
    tmpdir = tempfile.mkdtemp(prefix='test-uncompress-')
    with zipfile.ZipFile(archive_path) as zf:
        skipped = extract_zip_to_dir(zf, tmpdir)
    return tmpdir, skipped


def _assert_clean(path):
    # Must be a surrogate-free str that can reach a template / HTTP response.
    assert isinstance(path, str)
    path.encode('utf-8')  # would raise UnicodeEncodeError on a lone surrogate


# ----------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------
def test_normalize_pathname_strips_surrogates():
    surrogate = u'/tmp/\udc8b\udc8billegal/scrapy.cfg'
    with pytest.raises(UnicodeEncodeError):
        surrogate.encode('utf-8')

    cleaned = normalize_pathname(surrogate)
    cleaned.encode('utf-8')  # no longer raises
    assert u'\udc8b' not in cleaned

    clean = u'/tmp/demo - 副本/scrapy.cfg'
    assert normalize_pathname(clean) == clean


def test_decode_zip_member_filename_recovers_gbk():
    # cp936 bytes for "副本", as zipfile would expose them (cp437-decoded).
    moji = b'demo - \xb8\xb1\xb1\xbe - Win7CN/scrapy.cfg'.decode('cp437')
    assert decode_zip_member_filename(moji, 0) == u'demo - 副本 - Win7CN/scrapy.cfg'


def test_decode_zip_member_filename_recovers_utf8_without_flag():
    # macOS stores UTF-8 bytes but omits the EFS flag -> cp437 mojibake.
    moji = u'demo - 副本/x'.encode('utf-8').decode('cp437')
    assert decode_zip_member_filename(moji, 0) == u'demo - 副本/x'


def test_decode_zip_member_filename_trusts_efs_flag_and_keeps_ascii():
    assert decode_zip_member_filename(u'demo - 副本/x', ZIP_UTF8_FLAG) == u'demo - 副本/x'
    assert decode_zip_member_filename(u'outer/demo/scrapy.cfg', 0) == u'outer/demo/scrapy.cfg'


def test_decode_zip_member_filename_never_returns_surrogate():
    out = decode_zip_member_filename(u'efs/\udc8b\udc8b.txt', ZIP_UTF8_FLAG)
    out.encode('utf-8')
    assert u'\udc8b' not in out


# ----------------------------------------------------------------------------
# Windows / CN archives: extract + locate scrapy.cfg
# ----------------------------------------------------------------------------
@pytest.mark.parametrize('name', CN_ZIPS)
def test_cn_zip_locates_scrapy_cfg_with_recovered_name(name, fixture_extractor):
    archive = fixture_extractor(name)
    tmpdir, skipped = _uncompress(archive)

    assert skipped == []
    scrapy_cfg_path, searched = walk_for_scrapy_cfg(tmpdir)
    assert scrapy_cfg_path, "scrapy.cfg not found for %r, searched: %r" % (name, searched)
    assert os.path.exists(scrapy_cfg_path)
    _assert_clean(scrapy_cfg_path)

    # The Chinese directory name must be recovered (not left as mojibake), so the
    # extracted tree mirrors the original project layout.
    extracted = [normalize_pathname(p) for p in os.listdir(tmpdir)]
    assert any(u'副本' in p for p in extracted), extracted


@pytest.mark.parametrize('name', ASCII_ZIPS)
def test_ascii_zip_locates_scrapy_cfg(name, fixture_extractor):
    archive = fixture_extractor(name)
    tmpdir, skipped = _uncompress(archive)

    assert skipped == []
    scrapy_cfg_path, searched = walk_for_scrapy_cfg(tmpdir)
    assert scrapy_cfg_path, "scrapy.cfg not found for %r, searched: %r" % (name, searched)
    assert os.path.exists(scrapy_cfg_path)
    _assert_clean(scrapy_cfg_path)


# ----------------------------------------------------------------------------
# Nested project directories
# ----------------------------------------------------------------------------
def test_nested_outer_zip_resolves_project_root(fixture_extractor):
    # demo_outer.zip layout: outer/demo/scrapy.cfg (project root is 2 levels deep)
    archive = fixture_extractor('demo_outer.zip')
    tmpdir, skipped = _uncompress(archive)

    assert skipped == []
    scrapy_cfg_path, _ = walk_for_scrapy_cfg(tmpdir)
    assert scrapy_cfg_path and os.path.exists(scrapy_cfg_path)
    project_root = os.path.dirname(scrapy_cfg_path)
    assert os.path.basename(project_root) == 'demo'
    assert os.path.basename(os.path.dirname(project_root)) == 'outer'


def test_inner_zip_resolves_project_root(fixture_extractor):
    # demo_inner.zip layout: scrapy.cfg + demo/ at the archive root
    archive = fixture_extractor('demo_inner.zip')
    tmpdir, skipped = _uncompress(archive)

    assert skipped == []
    scrapy_cfg_path, _ = walk_for_scrapy_cfg(tmpdir)
    assert scrapy_cfg_path and os.path.exists(scrapy_cfg_path)
    assert os.path.dirname(scrapy_cfg_path) == os.path.abspath(tmpdir)


def test_without_scrapy_cfg_reports_searched_paths(fixture_extractor):
    archive = fixture_extractor('demo_without_scrapy_cfg.zip')
    tmpdir, skipped = _uncompress(archive)

    scrapy_cfg_path, searched = walk_for_scrapy_cfg(tmpdir)
    assert scrapy_cfg_path == ''
    assert searched, "searched paths should be reported for the failure message"
    for path in searched:
        _assert_clean(path)


# ----------------------------------------------------------------------------
# Mixed illegal names must not abort extraction or escape the tmpdir
# ----------------------------------------------------------------------------
def _build_mixed_illegal_zip(path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # A valid project nested under a clean ASCII directory.
        zf.writestr('proj/inner/scrapy.cfg', SCRAPY_CFG_CONTENT)
        zf.writestr('proj/inner/demo/__init__.py', '')
        # A cp936/gbk directory name (EFS flag off) carrying "副本".
        gbk_member = b'demo - \xb8\xb1\xb1\xbe/junk.txt'.decode('cp437')
        zf.writestr(zipfile.ZipInfo(gbk_member), 'x')
        # A member flagged UTF-8 with a non-ASCII name.
        efs = zipfile.ZipInfo(u'efsdir/文件.txt')
        efs.flag_bits |= ZIP_UTF8_FLAG
        zf.writestr(efs, 'x')
        # A backslash-separated name (Windows style) must be normalized.
        zf.writestr(zipfile.ZipInfo('win\\style\\path.txt'), 'x')
        # A zip-slip attempt must stay confined to tmpdir.
        zf.writestr(zipfile.ZipInfo('../escape.txt'), 'pwned')
    return path


def test_mixed_illegal_names_do_not_abort_and_locate_cfg(tmp_path):
    archive = _build_mixed_illegal_zip(str(tmp_path / 'mixed_illegal.zip'))
    tmpdir, skipped = _uncompress(archive)  # must not raise

    # scrapy.cfg is still located despite the illegal/mixed entries.
    scrapy_cfg_path, searched = walk_for_scrapy_cfg(tmpdir)
    assert scrapy_cfg_path and os.path.exists(scrapy_cfg_path)
    assert os.path.basename(os.path.dirname(scrapy_cfg_path)) == 'inner'

    # Nothing escaped the extraction directory.
    assert not os.path.exists(os.path.join(os.path.dirname(tmpdir), 'escape.txt'))

    # Backslash member was normalized into nested directories under tmpdir.
    assert os.path.exists(os.path.join(tmpdir, 'win', 'style', 'path.txt'))

    # Every extracted path is surrogate-free / UTF-8 encodable.
    for dirpath, dirnames, filenames in os.walk(tmpdir):
        for name in dirnames + filenames:
            normalize_pathname(os.path.join(dirpath, name)).encode('utf-8')


def test_walk_sanitizes_surrogate_searched_paths():
    # Emulate os.walk yielding an undecodable on-disk directory name.
    def fake_walk(top):
        yield (u'/tmp/\udc8b\udc8billegal', [], [])

    scrapy_cfg_path, searched = walk_for_scrapy_cfg('/whatever', walk=fake_walk)
    assert scrapy_cfg_path == ''
    assert searched
    for path in searched:
        path.encode('utf-8')  # sanitized, so no UnicodeEncodeError
        assert u'\udc8b' not in path
