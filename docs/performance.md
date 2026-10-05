# Performance verification

Verified on macOS with Python 3.12.10, PySide6 6.11.2 and FanFicFare 4.62.0 on 2026-10-04.

- Persistent workers reuse HTTP connections across compatible configurations. A loopback HTTP/1.1 test confirmed the same TCP client port across two requests made through separate configurations.
- The queue runs at most two jobs simultaneously. Tests verify that a third job waits, duplicate sources run sequentially, repeated previews reuse their worker, and cancelling one job removes its staging folder while the other finishes.
- Temporary SQLite reservations coordinate request pacing between processes. Tests verify distinct reservations for the same site, independent sites, preservation of an existing delay, and bypass on page-cache hits. FanFicFare sleeps and retry backoff remain enabled.
- Calculated EPUB word counts are cached by complete-file SHA-256. Tests verify that unchanged files skip chapter parsing and that changed bytes trigger a recount. Original books and backups retain their existing integrity safeguards.
- Metadata and progress updates modify the affected queue row. A 200-row test verifies that another row's items survive a metadata update.
- Counting uses a text parser instead of constructing another BeautifulSoup tree. Tests compare counts with the previous implementation for markup, entities, Unicode, comments, malformed HTML, script and style elements.

## Local counting benchmark

Run `.venv/bin/python scripts/benchmark.py` from the repository root. The fixture contains three synthetic chapters with 54,000 words and 570,255 characters. Five-run medians on this host:

| Counting implementation | Median time |
| --- | ---: |
| Previous BeautifulSoup tree | 0.1345 seconds |
| Text parser | 0.0424 seconds |

This is approximately **3.17× faster for local counting** on this fixture. The script also prints a cumulative CPU profile. Chapter contents are never rewritten by the counting function.

These measurements do not establish a live Literotica download speedup. Website response times, image downloads, required pacing, authentication and retries can still dominate. Windows and Linux execution remain unverified locally; their build workflow is provided.
