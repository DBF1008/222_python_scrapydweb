# coding: utf-8
from functools import partial
from io import BytesIO
import os
import re
import tempfile
import zipfile

from tests.utils import cst, req, switch_scrapyd, upload_file_deploy


def test_deploy_from_post(app, client):
    text, __ = req(app, client, view='deploy', kws=dict(node=1), data={'1': 'on', '2': 'on'})
    assert (re.search(r'id="checkbox_1".*?checked.*?/>', text, re.S)
            and re.search(r'id="checkbox_2".*?checked.*?/>', text, re.S))


def test_auto_packaging_select_option(app, client):
    ins = [
        '(14 projects)',
        u"var folders = ['demo - 副本', 'demo',",
        "var projects = ['demo-copy', 'demo',",
        '<div>%s<' % cst.PROJECT,
        u'<div>demo - 副本<',
        '<div>demo<',
        '<div>demo_only_scrapy_cfg<'
    ]
    nos = ['<div>demo_without_scrapy_cfg<']
    if not os.environ.get('DATA_PATH', ''):
        nos.append('<h3>No projects found')
    req(app, client, view='deploy', kws=dict(node=2), ins=ins, nos=nos)


# {'status': 'error', 'message': 'Traceback
# ...TypeError:...activate_egg(eggpath)...\'tuple\' object is not an iterator\r\n'}
# egg is not a ZIP file (if using curl, use egg=@path not egg=path)
def test_addversion(app, client):
    data = {
        '1': 'on',
        'checked_amount': '1',
        'project': 'fakeproject',
        'version': 'fakeversion',
        'file': (BytesIO(b'my file contents'), "fake.egg")
    }
    req(app, client, view='deploy.upload', kws=dict(node=2), data=data, ins=['Fail to deploy project', 'egg'])


# <!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
# <title>Redirecting...</title>
# <h1>Redirecting...</h1>
# <p>You should be redirected automatically to target URL:
# <a href="/1/schedule/demo/2018-01-01T01_01_01/">/1/schedule/demo/2018-01-01T01_01_01/</a>.  If not click the link.
def test_auto_packaging(app, client):
    data = {
        '1': 'on',
        'checked_amount': '1',
        'folder': cst.PROJECT,
        'project': cst.PROJECT,
        'version': cst.VERSION
    }
    req(app, client, view='deploy.upload', kws=dict(node=2), data=data,
        ins=['deploy results - ScrapydWeb', 'onclick="multinodeRunSpider();"', 'id="checkbox_1"'],
        nos='id="checkbox_2"')

    data.update({'2': 'on', 'checked_amount': '2'})
    req(app, client, view='deploy.upload', kws=dict(node=2), data=data,
        ins=['deploy results - ScrapydWeb', 'onclick="multinodeRunSpider();"', 'id="checkbox_1"', 'id="checkbox_2"'])


def test_auto_packaging_unicode(app, client):
    if cst.WINDOWS_NOT_CP936:
        return
    data = {
        '1': 'on',
        'checked_amount': '1',
        'folder': u'demo - 副本',
        'project': u'demo - 副本',
        'version': cst.VERSION,
    }
    req(app, client, view='deploy.upload', kws=dict(node=2), data=data, ins=['deploy results', 'demo_____'])


def test_scrapy_cfg(app, client):
    for folder, result in cst.SCRAPY_CFG_DICT.items():
        data = {
            '1': 'on',
            '2': 'on',
            'checked_amount': '2',
            'folder': folder,
            'project': cst.PROJECT,
            'version': cst.VERSION,
        }
        ins = ['fail - ScrapydWeb', result] if result else 'deploy results - ScrapydWeb'
        req(app, client, view='deploy.upload', kws=dict(node=2), data=data, ins=ins)


def test_scrapy_cfg_first_node_not_exist(app, client):
    switch_scrapyd(app)
    for folder, result in cst.SCRAPY_CFG_DICT.items():
        data = {
            '1': 'on',
            '2': 'on',
            'checked_amount': '2',
            'folder': folder,
            'project': cst.PROJECT,
            'version': cst.VERSION,
        }
        nos = []
        if folder == 'demo_only_scrapy_cfg' or not result:
            ins = ['fail - ScrapydWeb', 'the first selected node returned status']
        else:
            ins = ['fail - ScrapydWeb', result]
            nos = 'the first selected node returned status'
        req(app, client, view='deploy.upload', kws=dict(node=2), data=data, ins=ins, nos=nos)


def test_upload_file_deploy(app, client):
    upload_file_deploy_multinode = partial(upload_file_deploy, app=app, client=client, multinode=True)

    filenames = ['demo.egg', 'demo_inner.zip', 'demo_outer.zip',
                 'demo - Win7CNsendzipped.zip', 'demo - Win10cp1252.zip']
    if cst.WINDOWS_NOT_CP936:
        filenames.extend(['demo - Ubuntu.zip', 'demo - Ubuntu.tar.gz', 'demo - macOS.zip', 'demo - macOS.tar.gz'])
    else:
        filenames.extend([u'副本.zip', u'副本.tar.gz', u'副本.egg', u'demo - 副本 - Win7CN.zip',
                          u'demo - 副本 - Win7CNsendzipped.zip', u'demo - 副本 - Win10cp936.zip',
                          u'demo - 副本 - Ubuntu.zip', u'demo - 副本 - Ubuntu.tar.gz',
                          u'demo - 副本 - macOS.zip', u'demo - 副本 - macOS.tar.gz'])

    for filename in filenames:
        if filename == 'demo.egg':
            project = cst.PROJECT
            redirect_project = cst.PROJECT
        else:
            project = re.sub(r'\.egg|\.zip|\.tar\.gz', '', filename)
            project = 'demo_unicode' if project == u'副本' else project
            redirect_project = re.sub(cst.STRICT_NAME_PATTERN, '_', project)
        upload_file_deploy_multinode(filename=filename, project=project, redirect_project=redirect_project)

    for filename, alert in cst.SCRAPY_CFG_DICT.items():
        if alert:
            upload_file_deploy_multinode(filename='%s.zip' % filename, project=filename, alert=alert, fail=True)
        else:
            upload_file_deploy_multinode(filename='%s.zip' % filename, project=filename, redirect_project=filename)

    switch_scrapyd(app)

    for filename, alert in cst.SCRAPY_CFG_DICT.items():
        if filename == 'demo_only_scrapy_cfg' or not alert:
            alert = 'the first selected node returned status'
        upload_file_deploy_multinode(filename='%s.zip' % filename, project=filename, alert=alert, fail=True)


def test_deploy_xhr(app, client):
    upload_file_deploy(app, client, filename='demo.egg', project=cst.PROJECT, redirect_project=cst.PROJECT, multinode=False)
    kws = dict(
        node=1,
        eggname='%s_%s_from_file_demo.egg' % (cst.PROJECT, cst.VERSION),
        project=cst.PROJECT,
        version=cst.VERSION
    )
    req(app, client, view='deploy.xhr', kws=kws, jskws=dict(status=cst.OK, project=cst.PROJECT))


# ---------------------------------------------------------------------------
# Regression tests for Windows Chinese / illegal-path zip extraction (PY3)
# ---------------------------------------------------------------------------

import struct as _struct
import zlib as _zlib


def _build_raw_zip(entries):
    """Build a zip file from raw byte-level entries.

    *entries* is a list of (filename_bytes, content_bytes, flag_bits).
    *filename_bytes* are written verbatim into the local and central
    directory headers.  *flag_bits* controls the general purpose bit flag
    (bit 11 = UTF-8).  Returns the zip file as ``bytes``.
    """
    buf = bytearray()
    central_entries = []
    offset = 0

    for fname_bytes, data, flag_bits in entries:
        crc = _zlib.crc32(data) & 0xFFFFFFFF
        compressed = data  # stored (no compression)

        # --- Local file header ---
        local_header = _struct.pack(
            '<IHHHHHIIIHH',
            0x04034b50,       # local file header signature
            20,               # version needed to extract (2.0)
            flag_bits,        # general purpose bit flag
            0,                # compression method: stored
            0,                # last mod file time
            0,                # last mod file date
            crc,              # CRC-32
            len(compressed),  # compressed size
            len(data),        # uncompressed size
            len(fname_bytes), # file name length
            0,                # extra field length
        )
        buf += local_header
        buf += fname_bytes
        buf += compressed

        # --- Central directory entry (remember for later) ---
        central_entries.append((fname_bytes, data, flag_bits, crc, len(compressed), offset))
        offset += len(local_header) + len(fname_bytes) + len(compressed)

    # --- Central directory ---
    cd_offset = offset
    for fname_bytes, data, flag_bits, crc, comp_size, local_offset in central_entries:
        cd_entry = _struct.pack(
            '<IHHHHHHIIIHHHHHII',
            0x02014b50,       # central directory file header signature
            20,               # version made by (2.0, MS-DOS)
            20,               # version needed to extract
            flag_bits,        # general purpose bit flag
            0,                # compression method: stored
            0,                # last mod file time
            0,                # last mod file date
            crc,              # CRC-32
            comp_size,        # compressed size
            len(data),        # uncompressed size
            len(fname_bytes), # file name length
            0,                # extra field length
            0,                # file comment length
            0,                # disk number start
            0,                # internal file attributes
            0,                # external file attributes
            local_offset,     # relative offset of local header
        )
        buf += cd_entry
        buf += fname_bytes
        offset += len(cd_entry) + len(fname_bytes)

    cd_size = offset - cd_offset

    # --- End of central directory record ---
    eocd = _struct.pack(
        '<IHHHHIIH',
        0x06054b50,                  # end of central directory signature
        0,                           # number of this disk
        0,                           # disk where central directory starts
        len(central_entries),        # number of central directory records on this disk
        len(central_entries),        # total number of central directory records
        cd_size,                     # size of central directory
        cd_offset,                   # offset of start of central directory
        0,                           # comment length
    )
    buf += eocd
    return bytes(buf)


def _make_gbk_zip(zip_path, entries):
    """Create a zip file that mimics a Windows Chinese (GBK/cp936) zip.

    Each entry is (filename_unicode, content_bytes).  *filename_unicode* is
    the intended Chinese filename; it is encoded as GBK bytes in the zip
    header **without** the UTF-8 flag (bit 11), just like Windows zip tools
    produce.
    """
    raw_entries = []
    for name, content in entries:
        try:
            gbk_bytes = name.encode('gbk')
        except UnicodeEncodeError:
            gbk_bytes = name.encode('utf-8')
        raw_entries.append((gbk_bytes, content, 0))  # flag_bits=0: no UTF-8
    data = _build_raw_zip(raw_entries)
    with open(zip_path, 'wb') as f:
        f.write(data)
    return zip_path


def _make_surrogate_zip(zip_path, entries):
    """Create a zip file where some entries have the UTF-8 flag set but
    contain bytes that are invalid UTF-8, producing surrogate characters
    when Python's zipfile reads them back.

    Each entry is (filename_bytes_or_str, content_bytes, is_surrogate).
    If *is_surrogate* is True, *filename_bytes_or_str* must be raw bytes
    that are invalid UTF-8 — they are written with the UTF-8 flag ON so
    Python's zipfile will try to decode them as UTF-8 with
    ``surrogateescape``, producing surrogate code points.
    """
    raw_entries = []
    for name, content, is_surrogate in entries:
        if is_surrogate:
            fname_bytes = name if isinstance(name, bytes) else name.encode('utf-8')
            raw_entries.append((fname_bytes, content, 0x800))  # UTF-8 flag ON
        else:
            fname_str = name if isinstance(name, str) else name.decode('utf-8')
            fname_bytes = fname_str.encode('utf-8')
            raw_entries.append((fname_bytes, content, 0x800))  # UTF-8 flag ON for valid UTF-8
    data = _build_raw_zip(raw_entries)
    with open(zip_path, 'wb') as f:
        f.write(data)
    return zip_path


SCRAPY_CFG_CONTENT = b"""[settings]
default = myproject.settings

[deploy]
url = http://localhost:6800/
project = myproject
"""


def test_uncompress_windows_gbk_zip(app, client):
    """Test that a Windows-style GBK zip with Chinese directory names
    is extracted correctly and scrapy.cfg is found."""
    from scrapydweb.views.operations.deploy import DeployUploadView

    tmpdir = tempfile.mkdtemp(prefix='test-gbk-zip-')
    try:
        # Scenario 1: Chinese dir name with scrapy.cfg inside
        zip_path = os.path.join(tmpdir, 'chinese_root.zip')
        _make_gbk_zip(zip_path, [
            (u'中文项目/scrapy.cfg', SCRAPY_CFG_CONTENT),
            (u'中文项目/myproject/__init__.py', b''),
        ])

        with app.test_request_context():
            view = DeployUploadView()
            extracted = view.uncompress_to_tmpdir(zip_path)
            assert os.path.isdir(extracted)
            # The Chinese directory should have been decoded properly
            chinese_dir = os.path.join(extracted, u'中文项目')
            assert os.path.isdir(chinese_dir), \
                "Chinese directory not found: %s (contents: %s)" % (
                    chinese_dir, os.listdir(extracted))
            cfg = os.path.join(chinese_dir, 'scrapy.cfg')
            assert os.path.isfile(cfg), "scrapy.cfg not found under Chinese dir"

            # search_scrapy_cfg_path should find it
            view.scrapy_cfg_searched_paths = []
            view.search_scrapy_cfg_path(extracted)
            assert view.scrapy_cfg_path != '', "scrapy.cfg should be found"
            assert 'scrapy.cfg' in view.scrapy_cfg_path
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_uncompress_nested_scrapy_cfg(app, client):
    """Test that scrapy.cfg in a nested directory is found, and the
    shallowest match is preferred when multiple exist."""
    from scrapydweb.views.operations.deploy import DeployUploadView

    tmpdir = tempfile.mkdtemp(prefix='test-nested-zip-')
    try:
        # Scenario 2: nested project with multiple scrapy.cfg files
        zip_path = os.path.join(tmpdir, 'nested.zip')
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('outer/inner/scrapy.cfg', SCRAPY_CFG_CONTENT.decode())
            zf.writestr('outer/inner/myproject/__init__.py', '')
            zf.writestr('outer/deep/deeper/scrapy.cfg', SCRAPY_CFG_CONTENT.decode())

        with app.test_request_context():
            view = DeployUploadView()
            extracted = view.uncompress_to_tmpdir(zip_path)

            view.scrapy_cfg_searched_paths = []
            view.search_scrapy_cfg_path(extracted)
            assert view.scrapy_cfg_path != '', "scrapy.cfg should be found"
            # Should prefer the shallowest: outer/inner/scrapy.cfg
            assert 'outer' in view.scrapy_cfg_path and 'inner' in view.scrapy_cfg_path, \
                "Expected shallowest match (outer/inner), got: %s" % view.scrapy_cfg_path
            assert 'deeper' not in view.scrapy_cfg_path, \
                "Should prefer shallower match, got: %s" % view.scrapy_cfg_path
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_uncompress_mixed_illegal_and_valid(app, client):
    """Test that a zip containing both valid entries and entries with
    surrogate/illegal filenames still extracts the valid scrapy.cfg."""
    from scrapydweb.views.operations.deploy import DeployUploadView

    tmpdir = tempfile.mkdtemp(prefix='test-mixed-zip-')
    try:
        # Scenario 3: mix of valid scrapy.cfg and a surrogate-named entry
        zip_path = os.path.join(tmpdir, 'mixed.zip')
        _make_surrogate_zip(zip_path, [
            ('valid_project/scrapy.cfg', SCRAPY_CFG_CONTENT, False),
            ('valid_project/myproject/__init__.py', b'', False),
            (b'\x8b\x8billegal_dir/file.txt', b'junk', True),  # surrogate entry
        ])

        with app.test_request_context():
            view = DeployUploadView()
            extracted = view.uncompress_to_tmpdir(zip_path)

            view.scrapy_cfg_searched_paths = []
            view.search_scrapy_cfg_path(extracted)
            assert view.scrapy_cfg_path != '', \
                "scrapy.cfg should be found despite illegal sibling entries"
            assert 'valid_project' in view.scrapy_cfg_path
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_uncompress_zip_slip_protection(app, client):
    """Test that zip entries with path traversal (../) are skipped."""
    from scrapydweb.views.operations.deploy import DeployUploadView

    tmpdir = tempfile.mkdtemp(prefix='test-zipslip-')
    try:
        zip_path = os.path.join(tmpdir, 'zipslip.zip')
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('project/scrapy.cfg', SCRAPY_CFG_CONTENT.decode())
            # Path traversal entry — should be skipped
            zf.writestr('../../../etc/evil.txt', 'malicious')

        with app.test_request_context():
            view = DeployUploadView()
            extracted = view.uncompress_to_tmpdir(zip_path)

            view.scrapy_cfg_searched_paths = []
            view.search_scrapy_cfg_path(extracted)
            assert view.scrapy_cfg_path != '', "scrapy.cfg should still be found"
            assert 'project' in view.scrapy_cfg_path
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

