# coding: utf-8
"""Shared parser for Scrapyd /jobs HTML pages.

Used by both the backend polling subprocess (scrapydweb/utils/poll.py) and the
frontend Jobs view (scrapydweb/views/dashboard/jobs.py) to ensure consistent,
robust parsing that tolerates column additions, reordering, and minor HTML
structure changes across Scrapyd versions.

See also:
    scrapydweb/utils/poll.py
    scrapydweb/views/dashboard/jobs.py
"""
import re


# Ordered keys for job dicts — shared by all consumers.
# poll.py uses: project, spider, job, pid, finish
# jobs.py uses: all keys
JOB_KEYS = [
    'project', 'spider', 'job', 'pid', 'start',
    'runtime', 'finish', 'href_log', 'href_items',
]

# Extracts href URL from anchor tags like <a href='/logs/...'>Log</a>
HREF_PATTERN = re.compile(r"""href=['"](.+?)['"]""")

# Maps Scrapyd <th> header text (lowercased) to JOB_KEYS key names.
# Columns not in this map (e.g. 'Cancel') are ignored during parsing.
_HEADER_MAP = {
    'project': 'project',
    'spider': 'spider',
    'job': 'job',
    'pid': 'pid',
    'start': 'start',
    'runtime': 'runtime',
    'finish': 'finish',
    'log': 'href_log',
    'items': 'href_items',
}

# Regex building blocks
_THEAD_PATTERN = re.compile(r'<thead>.*?</thead>', re.S)
_TR_PATTERN = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.S)
_TD_PATTERN = re.compile(r'<td\b[^>]*>(.*?)</td>', re.S)
_TH_PATTERN = re.compile(r'<th\b[^>]*>(.*?)</th>', re.S)

# Legacy fallback: positional column map for old Scrapyd without <thead>.
# Maps cell index to JOB_KEYS key, assuming the standard 9-column layout:
# Project, Spider, Job, PID, Start, Runtime, Finish, Log, Items
_LEGACY_COLUMN_MAP = {
    0: 'project',
    1: 'spider',
    2: 'job',
    3: 'pid',
    4: 'start',
    5: 'runtime',
    6: 'finish',
    7: 'href_log',
    8: 'href_items',
}

# Legacy fallback regex — the original JOB_PATTERN kept for old Scrapyd HTML
# that lacks <thead> and uses a compact table layout.
_LEGACY_ROW_PATTERN = re.compile(r"""
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


def _empty_job():
    """Return a new job dict with all JOB_KEYS set to empty string."""
    return dict.fromkeys(JOB_KEYS, '')


def _extract_headers(html):
    """Extract column headers from <thead> block.

    Returns:
        (headers, stripped_html): headers is a list of column name strings
        (e.g. ['Project', 'Spider', ...]), stripped_html is the HTML with
        the <thead> block removed.  If no <thead> is found, headers is None.
    """
    m = _THEAD_PATTERN.search(html)
    if not m:
        return None, html

    thead_html = m.group(0)
    stripped_html = html[:m.start()] + html[m.end():]

    # Extract <th> text content from the header row
    ths = _TH_PATTERN.findall(thead_html)
    if not ths:
        return None, html

    # Strip any inner HTML tags from <th> content and normalize whitespace
    headers = [re.sub(r'<[^>]+>', '', th).strip() for th in ths]
    return headers, stripped_html


def _build_column_map(headers):
    """Build a mapping from cell index to JOB_KEYS key name.

    Unknown columns (e.g. 'Cancel') are skipped — they won't appear in
    the resulting job dicts.

    Returns:
        dict mapping int (cell index) to str (JOB_KEYS key), or None if
        no known columns were found.
    """
    column_map = {}
    for idx, header in enumerate(headers):
        key = _HEADER_MAP.get(header.lower().strip())
        if key is not None:
            column_map[idx] = key
    return column_map if column_map else None


def _extract_cells(tr_inner_html):
    """Extract <td> cell contents from inside a <tr> tag.

    Returns a list of strings (cell contents, may include HTML like anchor tags).
    Returns empty list if no <td> tags found (e.g. section header rows with <th>).
    """
    return _TD_PATTERN.findall(tr_inner_html)


def _row_to_dict(cells, column_map):
    """Map cell values to a job dict using the column map.

    Only keys present in column_map are set; all other JOB_KEYS default
    to empty string.
    """
    job = _empty_job()
    for idx, key in column_map.items():
        if idx < len(cells):
            job[key] = cells[idx]
    return job


def _parse_with_headers(html, headers):
    """Parse job rows using header-based column mapping (modern Scrapyd)."""
    column_map = _build_column_map(headers)
    if column_map is None:
        return []

    jobs = []
    for tr_match in _TR_PATTERN.finditer(html):
        tr_inner = tr_match.group(1)
        cells = _extract_cells(tr_inner)
        if not cells:
            # Skip rows without <td> cells (section separators with <th>, etc.)
            continue
        job = _row_to_dict(cells, column_map)
        jobs.append(job)
    return jobs


def _parse_legacy(html):
    """Parse job rows using positional regex (legacy Scrapyd without <thead>)."""
    # First try cell-based extraction for headerless HTML that still has
    # well-formed <tr>/<td> structure
    jobs = []
    found_any_td = False
    for tr_match in _TR_PATTERN.finditer(html):
        tr_inner = tr_match.group(1)
        cells = _extract_cells(tr_inner)
        if not cells:
            continue
        found_any_td = True
        # Use positional mapping: first N cells map to JOB_KEYS in order
        job = _empty_job()
        for idx, key in _LEGACY_COLUMN_MAP.items():
            if idx < len(cells):
                job[key] = cells[idx]
        jobs.append(job)

    if found_any_td:
        return jobs

    # Final fallback: the original regex pattern for unusual HTML structures
    jobs = []
    for match in _LEGACY_ROW_PATTERN.finditer(html):
        job = _empty_job()
        job['project'] = match.group('Project')
        job['spider'] = match.group('Spider')
        job['job'] = match.group('Job')
        job['pid'] = match.group('PID') or ''
        job['start'] = match.group('Start') or ''
        job['runtime'] = match.group('Runtime') or ''
        job['finish'] = match.group('Finish') or ''
        job['href_log'] = match.group('Log') or ''
        job['href_items'] = match.group('Items') or ''
        jobs.append(job)
    return jobs


def parse_scrapyd_jobs(html):
    """Parse Scrapyd /jobs HTML page into a list of job dicts.

    Each dict has keys defined in JOB_KEYS:
        project, spider, job, pid, start, runtime, finish, href_log, href_items

    Handles both modern Scrapyd (with <thead> headers, all columns always
    present as <td> cells) and legacy Scrapyd (no headers, positional columns).

    Unknown columns (e.g. Cancel) are automatically ignored.
    Section separator rows (e.g. <tr><th colspan="N">Pending</th></tr>) are skipped.

    Args:
        html: Raw HTML string from Scrapyd's /jobs endpoint.

    Returns:
        List of dicts, one per job row.
    """
    headers, stripped_html = _extract_headers(html)

    if headers is not None:
        return _parse_with_headers(stripped_html, headers)
    else:
        return _parse_legacy(stripped_html)
