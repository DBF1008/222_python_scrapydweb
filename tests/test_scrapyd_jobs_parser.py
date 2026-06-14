# coding: utf-8
"""Regression tests for scrapydweb/utils/scrapyd_jobs_parser.py.

Pure unit tests — no Flask app or live Scrapyd server required.
Tests cover: modern Scrapyd format, Cancel column, missing columns,
reordered columns, legacy (no header) format, HTML-escaped content,
extra/unknown columns, and edge cases.
"""
import pytest

from scrapydweb.utils.scrapyd_jobs_parser import (
    parse_scrapyd_jobs, JOB_KEYS, HREF_PATTERN,
)


# ---------------------------------------------------------------------------
# HTML fixtures — modelled on real Scrapyd website.py output
# ---------------------------------------------------------------------------

def _build_modern_html(headers, pending_rows, running_rows, finished_rows):
    """Helper to build a realistic Scrapyd /jobs HTML page."""
    ths = '\n'.join('            <th>%s</th>' % h for h in headers)
    colspan = len(headers)

    def _section(label, rows):
        sep = '            <tr>\n                <th colspan="%d">%s</th>\n            </tr>' % (colspan, label)
        return '        <tbody>\n%s\n%s\n        </tbody>' % (sep, '\n'.join(rows))

    def _row(cells):
        tds = '\n'.join('            <td>%s</td>' % c for c in cells)
        return '            <tr>\n%s\n            </tr>' % tds

    thead = '        <thead>\n            <tr>\n%s\n            </tr>\n        </thead>' % ths
    tbodies = '\n'.join([
        _section('Pending', [_row(r) for r in pending_rows]),
        _section('Running', [_row(r) for r in running_rows]),
        _section('Finished', [_row(r) for r in finished_rows]),
    ])

    return (
        '<!DOCTYPE html>\n'
        '<html>\n<head><title>Scrapyd</title></head>\n'
        '<body>\n'
        '    <h1>Jobs</h1>\n'
        '    <table id="jobs">\n'
        '%s\n%s\n'
        '    </table>\n'
        '</body>\n</html>'
    ) % (thead, tbodies)


# Standard 9-column headers (no Cancel)
_STANDARD_HEADERS = ['Project', 'Spider', 'Job', 'PID', 'Start', 'Runtime', 'Finish', 'Log', 'Items']

# Pending row: only Project, Spider, Job, rest are empty
_PENDING_CELLS = ['myproject', 'myspider', 'pending123', '', '', '', '', '', '']
# Running row
_RUNNING_CELLS = [
    'myproject', 'myspider', 'running456', '12345',
    '2024-01-15 10:30:00', '0:05:23', '',
    '<a href="/logs/myproject/myspider/running456.log">Log</a>',
    '<a href="/items/myproject/myspider/running456.jl">Items</a>',
]
# Finished row
_FINISHED_CELLS = [
    'myproject', 'myspider', 'finished789', '',
    '2024-01-15 09:00:00', '0:15:42', '2024-01-15 09:15:42',
    '<a href="/logs/myproject/myspider/finished789.log">Log</a>',
    '<a href="/items/myproject/myspider/finished789.jl">Items</a>',
]

MODERN_HTML = _build_modern_html(
    _STANDARD_HEADERS,
    pending_rows=[_PENDING_CELLS],
    running_rows=[_RUNNING_CELLS],
    finished_rows=[_FINISHED_CELLS],
)


# ---------------------------------------------------------------------------
# Tests: modern Scrapyd format (with <thead>)
# ---------------------------------------------------------------------------

class TestModernFormat:
    def test_multiple_jobs_parsed(self):
        """All three job rows (pending, running, finished) should be parsed."""
        jobs = parse_scrapyd_jobs(MODERN_HTML)
        assert len(jobs) == 3

    def test_job_dict_keys(self):
        """Every job dict should have all JOB_KEYS."""
        jobs = parse_scrapyd_jobs(MODERN_HTML)
        for job in jobs:
            assert set(job.keys()) == set(JOB_KEYS)

    def test_pending_job(self):
        """Pending job: pid/start/runtime/finish empty, project/spider/job present."""
        jobs = parse_scrapyd_jobs(MODERN_HTML)
        pending = jobs[0]
        assert pending['project'] == 'myproject'
        assert pending['spider'] == 'myspider'
        assert pending['job'] == 'pending123'
        assert pending['pid'] == ''
        assert pending['start'] == ''
        assert pending['runtime'] == ''
        assert pending['finish'] == ''
        assert pending['href_log'] == ''
        assert pending['href_items'] == ''

    def test_running_job(self):
        """Running job: all standard fields populated."""
        jobs = parse_scrapyd_jobs(MODERN_HTML)
        running = jobs[1]
        assert running['project'] == 'myproject'
        assert running['spider'] == 'myspider'
        assert running['job'] == 'running456'
        assert running['pid'] == '12345'
        assert running['start'] == '2024-01-15 10:30:00'
        assert running['runtime'] == '0:05:23'
        assert running['finish'] == ''
        assert 'href="/logs/myproject/myspider/running456.log"' in running['href_log']
        assert 'href="/items/myproject/myspider/running456.jl"' in running['href_items']

    def test_finished_job(self):
        """Finished job: all standard fields populated including finish."""
        jobs = parse_scrapyd_jobs(MODERN_HTML)
        finished = jobs[2]
        assert finished['project'] == 'myproject'
        assert finished['spider'] == 'myspider'
        assert finished['job'] == 'finished789'
        assert finished['pid'] == ''
        assert finished['start'] == '2024-01-15 09:00:00'
        assert finished['runtime'] == '0:15:42'
        assert finished['finish'] == '2024-01-15 09:15:42'
        assert 'href="/logs/myproject/myspider/finished789.log"' in finished['href_log']
        assert 'href="/items/myproject/myspider/finished789.jl"' in finished['href_items']

    def test_section_headers_skipped(self):
        """Section separator rows (<th colspan>) should not appear as jobs."""
        jobs = parse_scrapyd_jobs(MODERN_HTML)
        for job in jobs:
            # None of the parsed jobs should have section label text
            assert job['project'] not in ('Pending', 'Running', 'Finished')

    def test_href_pattern_extracts_url(self):
        """HREF_PATTERN should extract the URL from href_log/href_items content."""
        jobs = parse_scrapyd_jobs(MODERN_HTML)
        running = jobs[1]
        m = HREF_PATTERN.search(running['href_log'])
        assert m is not None
        assert m.group(1) == '/logs/myproject/myspider/running456.log'
        m = HREF_PATTERN.search(running['href_items'])
        assert m is not None
        assert m.group(1) == '/items/myproject/myspider/running456.jl'


# ---------------------------------------------------------------------------
# Tests: Cancel column (the key regression)
# ---------------------------------------------------------------------------

class TestCancelColumn:
    def _build_html_with_cancel(self):
        headers = _STANDARD_HEADERS + ['Cancel']
        cancel_button = (
            '<form method="post" action="/cancel.json">'
            '<input type="hidden" name="project" value="myproject">'
            '<input type="submit" value="Cancel">'
            '</form>'
        )
        pending = _PENDING_CELLS + [cancel_button]
        running = _RUNNING_CELLS + [cancel_button]
        finished = _FINISHED_CELLS + ['']  # finished jobs have empty Cancel
        return _build_modern_html(headers, [pending], [running], [finished])

    def test_cancel_column_ignored(self):
        """Cancel column should not appear in job dicts or affect other fields."""
        html = self._build_html_with_cancel()
        jobs = parse_scrapyd_jobs(html)
        assert len(jobs) == 3
        for job in jobs:
            assert 'cancel' not in job
            assert 'Cancel' not in job
            assert set(job.keys()) == set(JOB_KEYS)

    def test_pending_pid_not_cancel_button(self):
        """KEY REGRESSION: Pending job's pid must be empty, NOT Cancel button HTML.

        This was the core bug with the old positional regex — when Cancel was
        the 10th column, the regex would map the Cancel button HTML into the
        pid field (position 4), causing pending jobs to be misidentified as running.
        """
        html = self._build_html_with_cancel()
        jobs = parse_scrapyd_jobs(html)
        pending = jobs[0]
        assert pending['pid'] == ''
        assert '<form' not in pending['pid']
        assert 'Cancel' not in pending['pid']

    def test_running_fields_correct_with_cancel(self):
        """Running job fields should be correctly extracted even with Cancel column."""
        html = self._build_html_with_cancel()
        jobs = parse_scrapyd_jobs(html)
        running = jobs[1]
        assert running['pid'] == '12345'
        assert running['start'] == '2024-01-15 10:30:00'
        assert running['finish'] == ''

    def test_finished_fields_correct_with_cancel(self):
        """Finished job fields should be correctly extracted even with Cancel column."""
        html = self._build_html_with_cancel()
        jobs = parse_scrapyd_jobs(html)
        finished = jobs[2]
        assert finished['finish'] == '2024-01-15 09:15:42'
        assert finished['pid'] == ''


# ---------------------------------------------------------------------------
# Tests: missing optional columns
# ---------------------------------------------------------------------------

class TestMissingColumns:
    def test_no_items_column(self):
        """When items_dir is not local, Items column is absent."""
        headers = ['Project', 'Spider', 'Job', 'PID', 'Start', 'Runtime', 'Finish', 'Log']
        pending = ['myproject', 'myspider', 'pending1', '', '', '', '', '']
        running = [
            'myproject', 'myspider', 'running1', '999',
            '2024-01-15 10:00:00', '0:01:00', '',
            '<a href="/logs/myproject/myspider/running1.log">Log</a>',
        ]
        finished = [
            'myproject', 'myspider', 'finished1', '',
            '2024-01-15 09:00:00', '0:10:00', '2024-01-15 09:10:00',
            '<a href="/logs/myproject/myspider/finished1.log">Log</a>',
        ]
        html = _build_modern_html(headers, [pending], [running], [finished])
        jobs = parse_scrapyd_jobs(html)
        assert len(jobs) == 3
        for job in jobs:
            assert job['href_items'] == ''
        assert jobs[1]['href_log'] != ''
        assert jobs[2]['href_log'] != ''

    def test_no_log_no_items(self):
        """Edge case: both Log and Items columns absent."""
        headers = ['Project', 'Spider', 'Job', 'PID', 'Start', 'Runtime', 'Finish']
        running = ['proj', 'spi', 'j1', '42', '2024-01-01 00:00:00', '0:01:00', '']
        html = _build_modern_html(headers, [], [running], [])
        jobs = parse_scrapyd_jobs(html)
        assert len(jobs) == 1
        assert jobs[0]['href_log'] == ''
        assert jobs[0]['href_items'] == ''
        assert jobs[0]['pid'] == '42'


# ---------------------------------------------------------------------------
# Tests: reordered columns
# ---------------------------------------------------------------------------

class TestReorderedColumns:
    def test_columns_in_different_order(self):
        """Fields should be mapped by header name, not position."""
        headers = ['Job', 'Spider', 'Finish', 'Project', 'PID', 'Log', 'Start', 'Items', 'Runtime']
        # Cells in the same reordered sequence
        running = [
            'job_abc',          # Job
            'spider1',          # Spider
            '',                 # Finish (running)
            'proj1',            # Project
            '777',              # PID
            '<a href="/logs/x.log">Log</a>',  # Log
            '2024-06-01 12:00:00',  # Start
            '',                 # Items
            '0:02:00',          # Runtime
        ]
        pending = ['job_p', 'spider_p', '', 'proj_p', '', '', '', '', '']
        html = _build_modern_html(headers, [pending], [running], [])
        jobs = parse_scrapyd_jobs(html)
        assert len(jobs) == 2
        run = jobs[1]
        assert run['project'] == 'proj1'
        assert run['spider'] == 'spider1'
        assert run['job'] == 'job_abc'
        assert run['pid'] == '777'
        assert run['start'] == '2024-06-01 12:00:00'
        assert run['runtime'] == '0:02:00'
        assert run['finish'] == ''

        pend = jobs[0]
        assert pend['project'] == 'proj_p'
        assert pend['pid'] == ''


# ---------------------------------------------------------------------------
# Tests: extra unknown columns
# ---------------------------------------------------------------------------

class TestExtraColumns:
    def test_unknown_columns_between_known(self):
        """Unknown columns inserted between known ones should be ignored."""
        headers = ['Project', 'Spider', 'Custom1', 'Job', 'Priority', 'PID',
                   'Start', 'Runtime', 'Finish', 'Log', 'Items']
        running = [
            'proj', 'spi', 'custom_val', 'job1', 'high', '888',
            '2024-03-01 08:00:00', '1:00:00', '',
            '<a href="/logs/x.log">Log</a>',
            '<a href="/items/x.jl">Items</a>',
        ]
        pending = ['proj', 'spi', 'c1', 'job2', 'low', '', '', '', '', '', '']
        html = _build_modern_html(headers, [pending], [running], [])
        jobs = parse_scrapyd_jobs(html)
        assert len(jobs) == 2
        run = jobs[1]
        assert run['project'] == 'proj'
        assert run['spider'] == 'spi'
        assert run['job'] == 'job1'
        assert run['pid'] == '888'
        assert run['start'] == '2024-03-01 08:00:00'
        # Custom columns should not appear
        assert 'custom1' not in run
        assert 'priority' not in run
        assert 'Custom1' not in run


# ---------------------------------------------------------------------------
# Tests: legacy format (no <thead>)
# ---------------------------------------------------------------------------

class TestLegacyFormat:
    def test_legacy_nine_columns(self):
        """Legacy Scrapyd without <thead>, standard 9-column layout."""
        html = (
            '<html><body><h1>Jobs</h1><table>'
            '<tr>'
            '<td>proj</td><td>spi</td><td>j1</td><td>42</td>'
            '<td>2024-01-01 00:00:00</td><td>0:05:00</td><td></td>'
            '<td><a href="/logs/x.log">Log</a></td>'
            '<td><a href="/items/x.jl">Items</a></td>'
            '</tr>'
            '<tr>'
            '<td>proj</td><td>spi</td><td>j2</td><td></td>'
            '<td>2024-01-01 01:00:00</td><td>0:10:00</td>'
            '<td>2024-01-01 01:10:00</td>'
            '<td><a href="/logs/y.log">Log</a></td>'
            '<td></td>'
            '</tr>'
            '</table></body></html>'
        )
        jobs = parse_scrapyd_jobs(html)
        assert len(jobs) == 2
        # Running job
        assert jobs[0]['project'] == 'proj'
        assert jobs[0]['pid'] == '42'
        assert jobs[0]['finish'] == ''
        # Finished job
        assert jobs[1]['finish'] == '2024-01-01 01:10:00'
        assert jobs[1]['pid'] == ''

    def test_legacy_minimal_three_columns(self):
        """Legacy Scrapyd with only 3 columns (project, spider, job)."""
        html = (
            '<html><body><h1>Jobs</h1><table>'
            '<tr><td>proj</td><td>spi</td><td>j1</td></tr>'
            '</table></body></html>'
        )
        jobs = parse_scrapyd_jobs(html)
        assert len(jobs) == 1
        assert jobs[0]['project'] == 'proj'
        assert jobs[0]['spider'] == 'spi'
        assert jobs[0]['job'] == 'j1'
        assert jobs[0]['pid'] == ''
        assert jobs[0]['start'] == ''
        assert jobs[0]['href_log'] == ''
        assert jobs[0]['href_items'] == ''


# ---------------------------------------------------------------------------
# Tests: HTML-escaped content
# ---------------------------------------------------------------------------

class TestHTMLEscapedContent:
    def test_escaped_project_and_spider_names(self):
        """HTML-escaped characters in project/spider names should be parsed as-is."""
        headers = _STANDARD_HEADERS
        running = [
            'proj&amp;test', 'spi&lt;der&gt;', 'job1', '100',
            '2024-01-01 00:00:00', '0:01:00', '',
            '<a href="/logs/x.log">Log</a>',
            '',
        ]
        html = _build_modern_html(headers, [], [running], [])
        jobs = parse_scrapyd_jobs(html)
        assert len(jobs) == 1
        assert jobs[0]['project'] == 'proj&amp;test'
        assert jobs[0]['spider'] == 'spi&lt;der&gt;'

    def test_escaped_content_in_job_id(self):
        """HTML-escaped job ID should be parsed as-is."""
        headers = _STANDARD_HEADERS
        pending = ['proj', 'spi', 'job&quot;with&quot;quotes', '', '', '', '', '', '']
        html = _build_modern_html(headers, [pending], [], [])
        jobs = parse_scrapyd_jobs(html)
        assert jobs[0]['job'] == 'job&quot;with&quot;quotes'


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_table(self):
        """Valid HTML with headers but no data rows returns empty list."""
        headers = _STANDARD_HEADERS
        html = _build_modern_html(headers, [], [], [])
        jobs = parse_scrapyd_jobs(html)
        assert jobs == []

    def test_empty_html(self):
        """Completely empty HTML returns empty list."""
        jobs = parse_scrapyd_jobs('')
        assert jobs == []

    def test_no_table(self):
        """HTML without any table returns empty list."""
        jobs = parse_scrapyd_jobs('<html><body><h1>Jobs</h1></body></html>')
        assert jobs == []

    def test_multiple_running_jobs(self):
        """Multiple rows in the same section are all parsed."""
        headers = _STANDARD_HEADERS
        r1 = ['p1', 's1', 'j1', '1', '2024-01-01 00:00:00', '0:01:00', '', '', '']
        r2 = ['p2', 's2', 'j2', '2', '2024-01-01 00:00:01', '0:02:00', '', '', '']
        r3 = ['p3', 's3', 'j3', '3', '2024-01-01 00:00:02', '0:03:00', '', '', '']
        html = _build_modern_html(headers, [], [r1, r2, r3], [])
        jobs = parse_scrapyd_jobs(html)
        assert len(jobs) == 3
        assert [j['project'] for j in jobs] == ['p1', 'p2', 'p3']
        assert [j['pid'] for j in jobs] == ['1', '2', '3']

    def test_log_without_items_link(self):
        """Log link present but no items link (items file doesn't exist)."""
        headers = _STANDARD_HEADERS
        finished = [
            'proj', 'spi', 'j1', '',
            '2024-01-01 00:00:00', '0:10:00', '2024-01-01 00:10:00',
            '<a href="/logs/proj/spi/j1.log">Log</a>',
            '',
        ]
        html = _build_modern_html(headers, [], [], [finished])
        jobs = parse_scrapyd_jobs(html)
        assert jobs[0]['href_log'] != ''
        assert jobs[0]['href_items'] == ''

    def test_consumer_poll_compatibility(self):
        """Simulate how poll.py uses the parser: checks pid and finish truthiness."""
        html_with_cancel = _build_modern_html(
            _STANDARD_HEADERS + ['Cancel'],
            pending_rows=[_PENDING_CELLS + ['<form>Cancel</form>']],
            running_rows=[_RUNNING_CELLS + ['<form>Cancel</form>']],
            finished_rows=[_FINISHED_CELLS + ['']],
        )
        jobs = parse_scrapyd_jobs(html_with_cancel)
        running_jobs = []
        finished_jobs_set = set()
        for job in jobs:
            job_tuple = (job['project'], job['spider'], job['job'])
            if job['pid']:
                running_jobs.append(job_tuple)
            elif job['finish']:
                finished_jobs_set.add(job_tuple)
        # Pending job should NOT be classified as running (the old bug)
        assert len(running_jobs) == 1
        assert running_jobs[0] == ('myproject', 'myspider', 'running456')
        assert len(finished_jobs_set) == 1
        assert ('myproject', 'myspider', 'finished789') in finished_jobs_set

    def test_consumer_jobs_compatibility(self):
        """Simulate how jobs.py uses the parser: status determination."""
        jobs = parse_scrapyd_jobs(MODERN_HTML)
        for job in jobs:
            if not job['start']:
                status = '0'  # PENDING
            elif not job['finish']:
                status = '1'  # RUNNING
            else:
                status = '2'  # FINISHED
            job['_status'] = status
        assert jobs[0]['_status'] == '0'  # pending
        assert jobs[1]['_status'] == '1'  # running
        assert jobs[2]['_status'] == '2'  # finished
