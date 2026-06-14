# coding: utf-8
"""Regression tests for :func:`scrapydweb.utils.job_parser.parse_jobs`.

These tests deliberately need neither a running Scrapyd server nor the Flask
app: they feed hand-written snapshots of the Scrapyd "Jobs" page straight into
the parser.  They lock in robustness against the page-structure changes that
used to break the old positional ``JOB_PATTERN`` regex:

  * the legacy Scrapyd 1.2.x layout (the "old format");
  * a layout with extra columns -- both an appended "Cancel" button column and a
    column inserted in the *middle* (the "added column format");
  * layouts that omit optional columns/cells (the "missing optional column
    format").
"""
import re

from scrapydweb.utils.job_parser import JOB_KEYS, parse_jobs


# --------------------------------------------------------------------------- #
# Snapshots of the Scrapyd Jobs page in its various shapes.
# --------------------------------------------------------------------------- #

# Scrapyd 1.2.x: a plain <tr><th> header (no <thead>), nine columns, and rows
# that grow from 3 cells (pending) to the full set (running/finished).
LEGACY_HTML = """\
<html><body>
<h1>Jobs</h1>
<p><a href="/">Go back</a></p>
<table border='1'>
<tr><th>Project</th><th>Spider</th><th>Job</th><th>PID</th><th>Start</th>\
<th>Runtime</th><th>Finish</th><th>Log</th><th>Items</th></tr>
<tr><td>demo</td><td>test</td><td>0aa1</td></tr>
<tr><td>demo</td><td>test</td><td>1bb2</td><td>1001</td><td>2018-10-12 20:55:07</td>\
<td>0:01:00</td><td></td><td><a href='/logs/demo/test/1bb2.log'>Log</a></td><td></td></tr>
<tr><td>demo</td><td>test</td><td>2cc3</td><td></td><td>2018-10-12 20:50:00</td>\
<td>0:05:00</td><td>2018-10-12 20:55:00</td>\
<td><a href='/logs/demo/test/2cc3.log'>Log</a></td>\
<td><a href='/items/demo/test/2cc3.jl'>Items</a></td></tr>
</table>
</body></html>
"""

# Scrapyd 1.3.0+: header wrapped in <thead>, body in <tbody>, plus a trailing
# "Cancel" column whose cell carries a whole <form> (extra buttons).
EXTRA_TRAILING_COLUMN_HTML = """\
<html><body>
<h1>Jobs</h1>
<table>
<thead><tr><th>Project</th><th>Spider</th><th>Job</th><th>PID</th><th>Start</th>\
<th>Runtime</th><th>Finish</th><th>Log</th><th>Items</th><th>Cancel</th></tr></thead>
<tbody>
<tr><td>demo</td><td>test</td><td>0aa1</td><td></td><td></td><td></td><td></td><td></td><td></td>\
<td><form method="post" action="/cancel.json"><input type="hidden" name="project" value="demo">\
<input type="hidden" name="job" value="0aa1"><input type="submit" value="Cancel"></form></td></tr>
<tr><td>demo</td><td>test</td><td>1bb2</td><td>1001</td><td>2018-10-12 20:55:07</td>\
<td>0:01:00</td><td></td><td><a href="/logs/demo/test/1bb2.log">Log</a></td><td></td>\
<td><form method="post" action="/cancel.json"><input type="hidden" name="job" value="1bb2">\
<input type="submit" value="Cancel"></form></td></tr>
<tr><td>demo</td><td>test</td><td>2cc3</td><td></td><td>2018-10-12 20:50:00</td>\
<td>0:05:00</td><td>2018-10-12 20:55:00</td>\
<td><a href="/logs/demo/test/2cc3.log">Log</a></td>\
<td><a href="/items/demo/test/2cc3.jl">Items</a></td><td></td></tr>
</tbody>
</table>
</body></html>
"""

# A column ("Pages") inserted *between* Runtime and Finish.  The old positional
# regex would have shifted every following field; header-driven mapping must not.
EXTRA_MIDDLE_COLUMN_HTML = """\
<table>
<thead><tr><th>Project</th><th>Spider</th><th>Job</th><th>PID</th><th>Start</th>\
<th>Runtime</th><th>Pages</th><th>Finish</th><th>Log</th><th>Items</th></tr></thead>
<tbody>
<tr><td>demo</td><td>test</td><td>2cc3</td><td></td><td>2018-10-12 20:50:00</td>\
<td>0:05:00</td><td>42</td><td>2018-10-12 20:55:00</td>\
<td><a href="/logs/demo/test/2cc3.log">Log</a></td>\
<td><a href="/items/demo/test/2cc3.jl">Items</a></td></tr>
</tbody>
</table>
"""

# Optional column missing entirely: only eight columns, no "Items".
MISSING_ITEMS_COLUMN_HTML = """\
<table>
<tr><th>Project</th><th>Spider</th><th>Job</th><th>PID</th><th>Start</th>\
<th>Runtime</th><th>Finish</th><th>Log</th></tr>
<tr><td>demo</td><td>test</td><td>2cc3</td><td></td><td>2018-10-12 20:50:00</td>\
<td>0:05:00</td><td>2018-10-12 20:55:00</td>\
<td><a href='/logs/demo/test/2cc3.log'>Log</a></td></tr>
</table>
"""

# No header row at all and pending rows carrying only project/spider/job -- the
# parser must fall back to the canonical column order.
NO_HEADER_PENDING_HTML = """\
<table>
<tr><td>demo</td><td>test</td><td>0aa1</td></tr>
<tr><td>proj2</td><td>spider2</td><td>1bb2</td></tr>
</table>
"""


def _by_job(jobs, job_id):
    matches = [job for job in jobs if job['job'] == job_id]
    assert len(matches) == 1, "expected exactly one job %r, got %d" % (job_id, len(matches))
    return matches[0]


def _assert_canonical_keys(jobs):
    for job in jobs:
        assert set(job) == set(JOB_KEYS)


# --------------------------------------------------------------------------- #
# Old format (Scrapyd 1.2.x)
# --------------------------------------------------------------------------- #

def test_legacy_format_parses_all_states():
    jobs = parse_jobs(LEGACY_HTML)
    assert len(jobs) == 3
    _assert_canonical_keys(jobs)

    pending = _by_job(jobs, '0aa1')
    assert pending['project'] == 'demo' and pending['spider'] == 'test'
    assert pending['pid'] == '' and pending['start'] == '' and pending['finish'] == ''
    assert pending['href_log'] == '' and pending['href_items'] == ''

    running = _by_job(jobs, '1bb2')
    assert running['pid'] == '1001'
    assert running['start'] == '2018-10-12 20:55:07'
    assert running['runtime'] == '0:01:00'
    assert running['finish'] == ''  # running jobs have no finish time
    assert '/logs/demo/test/1bb2.log' in running['href_log']
    assert running['href_items'] == ''

    finished = _by_job(jobs, '2cc3')
    assert finished['pid'] == ''  # finished jobs report no pid
    assert finished['start'] == '2018-10-12 20:50:00'
    assert finished['finish'] == '2018-10-12 20:55:00'
    assert '/logs/demo/test/2cc3.log' in finished['href_log']
    assert '/items/demo/test/2cc3.jl' in finished['href_items']


# The exact regex/keys that jobs.py and poll.py used before this refactor, kept
# here so we can prove the new parser stays bug-for-bug compatible on the format
# it was originally written against.
_OLD_JOB_PATTERN = re.compile(r"""
                            <tr>\s*
                                <td>(?P<Project>.*?)</td>\s*
                                <td>(?P<Spider>.*?)</td>\s*
                                <td>(?P<Job>.*?)</td>\s*
                                (?:<td>(?P<PID>.*?)</td>\s*)?
                                (?:<td>(?P<Start>.*?)</td>\s*)?
                                (?:<td>(?P<Runtime>.*?)</td>\s*)?
                                (?:<td>(?P<Finish>.*?)</td>\s*)?
                                (?:<td>(?P<Log>.*?)</td>\s*)?
                                (?:<td>(?P<Items>.*?)</td>\s*)?
                                [\w\W]*?
                            </tr>
                          """, re.X)
_OLD_JOB_KEYS = ['project', 'spider', 'job', 'pid', 'start', 'runtime', 'finish', 'href_log', 'href_items']


def _parse_jobs_old_way(html):
    text = re.sub(r'<thead>.*?</thead>', '', html, flags=re.S)
    return [dict(zip(_OLD_JOB_KEYS, m)) for m in re.findall(_OLD_JOB_PATTERN, text)]


def test_legacy_format_matches_old_regex_exactly():
    # Backward-compatibility anchor: identical output on the legacy layout.
    assert parse_jobs(LEGACY_HTML) == _parse_jobs_old_way(LEGACY_HTML)


# --------------------------------------------------------------------------- #
# Added column format (Scrapyd 1.3.0+)
# --------------------------------------------------------------------------- #

def test_extra_trailing_cancel_column_is_ignored():
    jobs = parse_jobs(EXTRA_TRAILING_COLUMN_HTML)
    assert len(jobs) == 3
    _assert_canonical_keys(jobs)

    pending = _by_job(jobs, '0aa1')
    assert pending['pid'] == '' and pending['start'] == '' and pending['finish'] == ''
    # The whole <form>/<input value="Cancel"> cell must not leak into any field.
    assert all('Cancel' not in pending[key] for key in JOB_KEYS)
    assert all('<form' not in pending[key] for key in JOB_KEYS)

    running = _by_job(jobs, '1bb2')
    assert running['pid'] == '1001' and running['finish'] == ''
    assert '/logs/demo/test/1bb2.log' in running['href_log']
    assert 'Cancel' not in running['href_items'] and running['href_items'] == ''

    finished = _by_job(jobs, '2cc3')
    assert finished['finish'] == '2018-10-12 20:55:00'
    assert '/items/demo/test/2cc3.jl' in finished['href_items']


def test_extra_middle_column_does_not_shift_following_fields():
    # The strongest robustness check: a "Pages" column sits between Runtime and
    # Finish.  Finish must remain the timestamp (not "42"), and the link columns
    # must still resolve -- impossible with the old positional matching.
    jobs = parse_jobs(EXTRA_MIDDLE_COLUMN_HTML)
    assert len(jobs) == 1
    finished = _by_job(jobs, '2cc3')
    assert finished['start'] == '2018-10-12 20:50:00'
    assert finished['runtime'] == '0:05:00'
    assert finished['finish'] == '2018-10-12 20:55:00'
    assert finished['finish'] != '42'
    assert '/logs/demo/test/2cc3.log' in finished['href_log']
    assert '/items/demo/test/2cc3.jl' in finished['href_items']


# --------------------------------------------------------------------------- #
# Missing optional column format
# --------------------------------------------------------------------------- #

def test_missing_items_column_defaults_to_empty():
    jobs = parse_jobs(MISSING_ITEMS_COLUMN_HTML)
    assert len(jobs) == 1
    finished = _by_job(jobs, '2cc3')
    assert finished['finish'] == '2018-10-12 20:55:00'
    assert '/logs/demo/test/2cc3.log' in finished['href_log']
    assert finished['href_items'] == ''  # the column simply does not exist


def test_missing_optional_cells_without_header_use_positional_fallback():
    jobs = parse_jobs(NO_HEADER_PENDING_HTML)
    assert len(jobs) == 2
    _assert_canonical_keys(jobs)
    first = _by_job(jobs, '0aa1')
    assert first['project'] == 'demo' and first['spider'] == 'test'
    assert first['pid'] == '' and first['start'] == '' and first['finish'] == ''
    second = _by_job(jobs, '1bb2')
    assert second['project'] == 'proj2' and second['spider'] == 'spider2'


# --------------------------------------------------------------------------- #
# Minor HTML structure variations
# --------------------------------------------------------------------------- #

def test_tolerates_whitespace_attributes_and_newlines():
    html = """
    <table>
      <tr class="header"><th> Project </th><th>Spider</th><th>Job</th><th>PID</th>
          <th>Start</th><th>Runtime</th><th>Finish</th><th>Log</th><th>Items</th></tr>
      <tr class="odd">
          <td>  demo  </td>
          <td>\ttest\t</td>
          <td>
              2cc3
          </td>
          <td></td>
          <td>2018-10-12 20:50:00</td>
          <td>0:05:00</td>
          <td>2018-10-12 20:55:00</td>
          <td> <a href="/logs/demo/test/2cc3.log">Log</a> </td>
          <td><a href="/items/demo/test/2cc3.jl">Items</a></td>
      </tr>
    </table>
    """
    jobs = parse_jobs(html)
    assert len(jobs) == 1
    job = jobs[0]
    assert job['project'] == 'demo'
    assert job['spider'] == 'test'
    assert job['job'] == '2cc3'
    assert job['finish'] == '2018-10-12 20:55:00'
    assert '/logs/demo/test/2cc3.log' in job['href_log']
    assert '/items/demo/test/2cc3.jl' in job['href_items']


def test_unescapes_html_entities_in_text_fields():
    html = """\
<table>
<tr><th>Project</th><th>Spider</th><th>Job</th></tr>
<tr><td>a&amp;b</td><td>x&lt;y&gt;z</td><td>job&#39;1</td></tr>
</table>
"""
    jobs = parse_jobs(html)
    assert len(jobs) == 1
    job = jobs[0]
    assert job['project'] == 'a&b'
    assert job['spider'] == 'x<y>z'
    assert job['job'] == "job'1"


def test_empty_and_rowless_input_return_empty_list():
    assert parse_jobs('') == []
    assert parse_jobs(None) == []
    assert parse_jobs('<html><body><h1>Jobs</h1><table></table></body></html>') == []


def test_section_header_rows_are_skipped():
    # Some Scrapyd builds emit "Pending"/"Running"/"Finished" divider rows made
    # of a single <th colspan=...>; those carry no <td> and must be ignored.
    html = """\
<table>
<tr><th>Project</th><th>Spider</th><th>Job</th><th>PID</th><th>Start</th>\
<th>Runtime</th><th>Finish</th><th>Log</th><th>Items</th></tr>
<tr><th colspan="9">Running</th></tr>
<tr><td>demo</td><td>test</td><td>1bb2</td><td>1001</td><td>2018-10-12 20:55:07</td>\
<td>0:01:00</td><td></td><td><a href="/logs/demo/test/1bb2.log">Log</a></td><td></td></tr>
<tr><th colspan="9">Finished</th></tr>
<tr><td>demo</td><td>test</td><td>2cc3</td><td></td><td>2018-10-12 20:50:00</td>\
<td>0:05:00</td><td>2018-10-12 20:55:00</td>\
<td><a href="/logs/demo/test/2cc3.log">Log</a></td>\
<td><a href="/items/demo/test/2cc3.jl">Items</a></td></tr>
</table>
"""
    jobs = parse_jobs(html)
    assert [job['job'] for job in jobs] == ['1bb2', '2cc3']
    assert _by_job(jobs, '1bb2')['pid'] == '1001'
    assert _by_job(jobs, '2cc3')['finish'] == '2018-10-12 20:55:00'


def test_classification_semantics_used_by_callers():
    # poll.py / jobs.py distinguish states purely via these fields:
    #   pid truthy        -> running
    #   finish truthy     -> finished
    #   neither           -> pending
    for html in (LEGACY_HTML, EXTRA_TRAILING_COLUMN_HTML):
        jobs = parse_jobs(html)
        pending = _by_job(jobs, '0aa1')
        running = _by_job(jobs, '1bb2')
        finished = _by_job(jobs, '2cc3')
        assert not pending['pid'] and not pending['finish']
        assert running['pid'] and not running['finish']
        assert not finished['pid'] and finished['finish']
