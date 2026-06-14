# coding: utf-8
"""Robust parser for the Scrapyd "Jobs" page HTML.

Shared by both consumers of that page so they can never drift apart:
  * ``scrapydweb/utils/poll.py``            -- the background monitor subprocess
  * ``scrapydweb/views/dashboard/jobs.py``  -- the web UI

Historically each of those modules kept its own copy of a single positional
regex that matched a *fixed* sequence of ``<td>`` cells.  That approach was
fragile: it broke whenever Scrapyd added a column (e.g. the "Cancel" column in
1.3.0), wrapped the header in ``<thead>``, reordered columns or otherwise
tweaked the markup -- and the two copies could silently diverge.

This module parses the table structurally instead:
  * every ``<tr>`` row is scanned (``<thead>``/``<tbody>`` wrappers and section
    header rows such as "Pending"/"Running"/"Finished" are handled naturally);
  * the column order is derived from the table header (``<th>`` cells) so extra
    or reordered columns are matched by *name* rather than by position, falling
    back to Scrapyd's canonical column order when no header is present;
  * missing optional cells (e.g. pending rows that only carry
    project/spider/job), surrounding whitespace and HTML-escaped content are all
    tolerated.

The module deliberately depends on the standard library only, because
``poll.py`` is launched as a standalone script (see
``scrapydweb/utils/sub_process.py``) and must not import the Flask app or the
database layer.
"""
import re

try:
    from html import unescape as _html_unescape  # Python 3
except ImportError:  # pragma: no cover - Python 2 (still on the CI matrix)
    from HTMLParser import HTMLParser
    _html_unescape = HTMLParser().unescape


# Canonical keys returned for every job, in Scrapyd's default column order.
# Kept here as the single source of truth for both consumers.
JOB_KEYS = ['project', 'spider', 'job', 'pid', 'start', 'runtime', 'finish', 'href_log', 'href_items']

# Columns whose raw cell HTML (e.g. "<a href='/logs/p/s/j.log'>Log</a>") is kept
# verbatim so the caller can extract the href itself (see HREF_PATTERN in jobs.py).
_HREF_KEYS = ('href_log', 'href_items')

# Map a normalized Scrapyd header label to our canonical key.  Any column that is
# not listed here (e.g. "cancel", "action", "stop", "pages") is ignored on
# purpose, which is exactly what makes extra/reordered columns harmless.
_HEADER_TO_KEY = {
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

_ROW_PATTERN = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.I | re.S)
# Backreference \1 keeps <td>..</td> and <th>..</th> balanced; re.I makes it
# case-insensitive. Nested anchors/forms inside a cell are fine because they use
# their own closing tags, not </td>.
_CELL_PATTERN = re.compile(r'<(td|th)\b[^>]*>(.*?)</\1>', re.I | re.S)
_TAG_PATTERN = re.compile(r'<[^>]+>')


def _clean_text(html):
    """Strip tags, unescape HTML entities and trim surrounding whitespace."""
    return _html_unescape(_TAG_PATTERN.sub('', html)).strip()


def _row_cells(row_html):
    """Return ``(tag, inner_html)`` tuples for every ``<td>``/``<th>`` in a row."""
    return _CELL_PATTERN.findall(row_html)


def _resolve_columns(rows_cells):
    """Work out the canonical key for each cell position.

    Prefer the table header: the first row whose ``<th>`` cells include a
    recognizable column ("project").  This lets us map columns by name, so an
    extra column anywhere (not just at the end) does not shift the others.
    Fall back to Scrapyd's default column order when no usable header exists.
    """
    for cells in rows_cells:
        labels = [_clean_text(inner).lower() for (tag, inner) in cells if tag.lower() == 'th']
        if 'project' in labels:
            return [_HEADER_TO_KEY.get(label) for label in labels]
    return list(JOB_KEYS)


def parse_jobs(text):
    """Parse Scrapyd Jobs-page HTML into a list of job dicts.

    Each dict always carries every key in :data:`JOB_KEYS`; cells that are absent
    (e.g. a pending row, or a column Scrapyd does not render) default to ''.
    ``href_log``/``href_items`` keep the raw cell HTML so the caller can extract
    the href; all other fields are plain, unescaped, whitespace-trimmed text.
    """
    rows_cells = [_row_cells(row) for row in _ROW_PATTERN.findall(text or '')]
    columns = _resolve_columns(rows_cells)

    jobs = []
    for cells in rows_cells:
        td_cells = [inner for (tag, inner) in cells if tag.lower() == 'td']
        if not td_cells:
            continue  # column header, section divider ("Running"), or empty row
        job = dict.fromkeys(JOB_KEYS, '')
        for index, inner in enumerate(td_cells):
            key = columns[index] if index < len(columns) else None
            if not key or key not in JOB_KEYS:
                continue  # unmapped / extra column (e.g. the Cancel button)
            if key in _HREF_KEYS:
                job[key] = inner.strip()
            else:
                job[key] = _clean_text(inner)
        jobs.append(job)
    return jobs
