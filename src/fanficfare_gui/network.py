"""Coordinate uncached requests across the desktop's worker processes."""

import sqlite3
import time
from contextlib import closing
from urllib.parse import urlparse


def initialize_pacing(path):
    with closing(sqlite3.connect(path, timeout=30)) as database, database:
        database.execute("CREATE TABLE IF NOT EXISTS pacing (site TEXT PRIMARY KEY, next REAL, interval REAL)")


class SitePacer:
    def __init__(self, path, clock=time.monotonic, sleep=time.sleep):
        self.path = path
        self.clock = clock
        self.sleep = sleep

    def wait(self, site, interval, emit):
        # Reserve before sleeping, releasing the database lock immediately.
        # Only host names and monotonic timestamps enter this temporary file.
        with closing(sqlite3.connect(self.path, timeout=30)) as database, database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute("SELECT next, interval FROM pacing WHERE site=?", (site,)).fetchone()
            now = self.clock()
            start = max(now, row[0]) if row else now
            spacing = max(interval, row[1]) if row and row[0] > now else interval
            database.execute("INSERT OR REPLACE INTO pacing VALUES (?, ?, ?)", (site, start + spacing, spacing))
        delay = start - self.clock()
        if delay > 0:
            emit({"type": "activity", "percent": None, "message": f"Waiting for {site} request pacing…"})
            self.sleep(delay)


def attach_pacing(config, path, emit):
    if not path:
        return
    fetcher = config.get_fetcher()
    transport = fetcher.request
    pacer = SitePacer(path)

    def request(method, url, *args, **kwargs):
        if urlparse(url).scheme in {"http", "https"}:
            # Use the larger of the configured delay and an adapter's override.
            # FanFicFare's own random sleeps and retry backoff stay in place.
            interval = max(0, float(fetcher.getConfig("slow_down_sleep_time", 0) or 0),
                           float(config.sleeper.sleep_override or 0))
            site = config.site if config.site != "unknown" else (urlparse(url).hostname or "unknown")
            site = site.lower().removeprefix("www.")
            pacer.wait(site, interval, emit)
        return transport(method, url, *args, **kwargs)

    # Cache decorators sit outside request(), so cache hits consume no slot.
    fetcher.request = request
