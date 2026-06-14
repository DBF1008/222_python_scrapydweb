# Fix: Windows Chinese/Illegal Path Zip Compatibility in ScrapydWeb Deploy

## Context

When ScrapydWeb on Python 3 extracts zip files created on Windows with Chinese (GBK/cp936) filenames, `zipfile.extractall()` misdecodes the filenames. Windows zip tools encode Chinese filenames as GBK bytes **without** setting the UTF-8 flag (bit 11). Python 3's zipfile then decodes those GBK bytes as CP437, producing garbled directory names. This causes `search_scrapy_cfg_path()` to fail to find `scrapy.cfg`, breaking auto-packaging deployment.

Additionally, some corrupted filenames produce **surrogate characters** in paths, which crash `os.walk()`, `pformat()`, and other string operations. The current code only catches `UnicodeDecodeError` (a PY2-era concern), missing `UnicodeEncodeError` that surrogates trigger on PY3.

## Root Cause

1. **`uncompress_to_tmpdir()` PY3 branch** (line 378): bare `f.extractall(tmpdir)` — no encoding fixup
2. **`search_scrapy_cfg_path()`** (line 398): only catches `UnicodeDecodeError`, not `UnicodeEncodeError` from surrogate paths
3. **`dispatch_request()`** (line 228): `pformat(self.scrapy_cfg_searched_paths)` crashes on surrogate paths
4. **No shallowest-match preference**: when multiple `scrapy.cfg` exist, result depends on filesystem walk order

## Files to Modify

- `scrapydweb/views/operations/deploy.py` — main fix
- `tests/test_deploy.py` — regression tests (new test function)

## Implementation

### 1. `uncompress_to_tmpdir()` — PY3 zip extraction with encoding fixup

Replace the bare `f.extractall(tmpdir)` on line 378 with a manual extraction loop:

```python
else:
    # PY3: manual extraction with encoding fixup for Windows GBK zips
    for zip_info in f.infolist():
        filename = zip_info.filename
        # If UTF-8 flag (bit 11) is NOT set, Python decoded as cp437.
        # Re-encode to raw bytes and try GBK (common for Windows CN).
        if not (zip_info.flag_bits & 0x800):
            try:
                raw = filename.encode('cp437')
                filename = raw.decode('gbk')
            except (UnicodeDecodeError, UnicodeEncodeError):
                try:
                    filename = raw.decode('utf-8')
                except (UnicodeDecodeError, UnicodeEncodeError):
                    pass  # keep cp437-decoded name as last resort
        # Sanitize: reject paths with surrogates or absolute/.. components
        if _has_surrogates(filename):
            self.logger.warning("Skipping zip entry with surrogate chars: %r", zip_info.filename)
            continue
        target = os.path.normpath(os.path.join(tmpdir, filename))
        # Prevent zip-slip
        if not target.startswith(os.path.normpath(tmpdir) + os.sep) and target != os.path.normpath(tmpdir):
            self.logger.warning("Skipping zip entry with unsafe path: %r", filename)
            continue
        if zip_info.is_dir():
            os.makedirs(target, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with f.open(zip_info) as src, open(target, 'wb') as dst:
                copyfileobj(src, dst)
```

Add a module-level helper `_has_surrogates()`:
```python
def _has_surrogates(s):
    try:
        s.encode('utf-8')
        return False
    except UnicodeEncodeError:
        return True
```

### 2. `search_scrapy_cfg_path()` — catch `UnicodeEncodeError` + prefer shallowest match

- Change `except UnicodeDecodeError:` → `except (UnicodeDecodeError, UnicodeEncodeError):`
- Change the PY3 fallback: instead of `raise`, use a safe walk that skips directories/files with surrogate paths
- Add shallowest-match logic: collect all `scrapy.cfg` candidates, pick the one with the shortest path depth

```python
def search_scrapy_cfg_path(self, search_path, func_walk=os.walk, retry=True):
    try:
        candidates = []
        for dirpath, dirnames, filenames in func_walk(search_path):
            # Skip directories with surrogate characters
            if _has_surrogates(dirpath):
                continue
            self.scrapy_cfg_searched_paths.append(os.path.abspath(dirpath))
            if 'scrapy.cfg' in filenames:
                cfg_path = os.path.abspath(os.path.join(dirpath, 'scrapy.cfg'))
                candidates.append(cfg_path)
        if candidates:
            # Prefer the shallowest match (fewest path components from search_path)
            self.scrapy_cfg_path = min(candidates, key=lambda p: p.count(os.sep))
            self.logger.debug("scrapy_cfg_path: %s", self.scrapy_cfg_path)
        else:
            self.logger.error("scrapy.cfg not found in: %s", search_path)
            self.scrapy_cfg_path = ''
    except (UnicodeDecodeError, UnicodeEncodeError):
        msg = "Found illegal filenames in %s" % search_path
        self.logger.error(msg)
        flash(msg, self.WARN)
        if PY2 and retry:
            self.search_scrapy_cfg_path(search_path, func_walk=self.safe_walk, retry=False)
        elif retry:
            self.search_scrapy_cfg_path(search_path, func_walk=self._safe_walk_py3, retry=False)
        else:
            raise
```

Add `_safe_walk_py3` method that wraps `os.walk` but catches `OSError`/`UnicodeError` per-directory and skips entries with surrogate names.

### 3. `dispatch_request()` — sanitize paths in error reporting

Wrap the `pformat` call (line 228) to handle surrogate paths:

```python
safe_paths = []
for p in self.scrapy_cfg_searched_paths:
    try:
        p.encode('utf-8')
        safe_paths.append(p)
    except UnicodeEncodeError:
        safe_paths.append(p.encode('utf-8', 'replace').decode('utf-8'))
message = "scrapy_cfg_searched_paths:\n%s" % pformat(safe_paths)
```

### 4. Regression Tests

Add a new test function `test_uncompress_windows_chinese_zip` in `tests/test_deploy.py` that:

1. **Programmatically creates** zip files mimicking Windows GBK encoding (no UTF-8 flag, GBK-encoded Chinese directory names containing `scrapy.cfg`)
2. Tests three scenarios:
   - **Windows GBK zip with Chinese dir**: zip entry with GBK bytes for `中文项目/scrapy.cfg`, no UTF-8 flag
   - **Nested project dir**: zip with `outer/inner/scrapy.cfg` structure
   - **Mixed illegal + valid paths**: zip containing both a valid `scrapy.cfg` path and entries with illegal byte sequences
3. Calls `uncompress_to_tmpdir()` and `search_scrapy_cfg_path()` directly on a `DeployUploadView` instance
4. Asserts `scrapy_cfg_path` is found and the path is valid UTF-8

## Verification

1. Run the new regression test: `pytest tests/test_deploy.py::test_uncompress_windows_chinese_zip -v`
2. Run existing deploy tests to ensure no regressions: `pytest tests/test_deploy.py -v`
3. Verify the fix handles: GBK→UTF-8 transcoding, surrogate sanitization, zip-slip prevention, shallowest-match preference
