"""Bounded metadata, connection and word-count reuse within one worker."""

from collections import OrderedDict
import hashlib
from pathlib import Path
import time

from fanficfare.fetchers.cache_basic import BasicCache
from fanficfare.fetchers.fetcher_requests import RequestsFetcher
from fanficfare.fetchers.fetcher_cloudscraper import CloudScraperFetcher


TTL = 300
MAX_PAGE_BYTES = 16 * 1024 * 1024


class RecentPages(BasicCache):
    def __init__(self, clock=time.monotonic):
        super().__init__()
        self.clock = clock
        self.times = {}
        self.metadata_keys = set()
        self.capture_metadata = True
        self.bytes = 0

    def begin_job(self):
        now = self.clock()
        keep = {key for key in self.metadata_keys if now - self.times.get(key, 0) < TTL}
        self.basic_cache = {key: value for key, value in self.basic_cache.items() if key in keep}
        self.times = {key: value for key, value in self.times.items() if key in keep}
        self.metadata_keys = keep
        self.bytes = sum(len(value[0]) for value in self.basic_cache.values())
        self.capture_metadata = True

    def has_cachekey(self, key):
        return self.clock() - self.times.get(key, -TTL) < TTL and super().has_cachekey(key)

    def set_to_cache(self, key, data, redirectedurl):
        # Do not keep unbounded story/image data in a long-running process.
        size = len(data)
        if size > MAX_PAGE_BYTES:
            return
        if key in self.basic_cache:
            self.bytes -= len(self.basic_cache.pop(key)[0])
        while self.basic_cache and self.bytes + size > MAX_PAGE_BYTES:
            oldest = min(self.times, key=self.times.get)
            self.bytes -= len(self.basic_cache.pop(oldest)[0])
            self.times.pop(oldest, None)
            self.metadata_keys.discard(oldest)
        super().set_to_cache(key, data, redirectedurl)
        self.bytes += size
        self.times[key] = self.clock()
        if self.capture_metadata:
            self.metadata_keys.add(key)


class Session:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.groups = OrderedDict()
        self.previews = OrderedDict()
        self.connections = OrderedDict()
        self.word_counts = OrderedDict()

    def scope(self, request, config):
        ini = request.get("ini")
        fingerprint = hashlib.sha256(Path(ini).expanduser().read_bytes()).hexdigest() if ini else "defaults"
        # Include format and confirmation so settings/authentication do not cross.
        # Per-story INI sections can change credentials and proxy settings.
        # Include only sections that actually exist so ordinary stories on
        # the same site still share their connection and metadata pages.
        story_sections = tuple(section for section in config.sectionslist
                               if section.startswith(("http://", "https://")) and config.has_section(section))
        return (config.site, request.get("format", "epub"), fingerprint, bool(request.get("adult")), story_sections)

    def pages(self, scope):
        if scope not in self.groups:
            self.groups[scope] = (RecentPages(self.clock), None)
        self.groups.move_to_end(scope)
        while len(self.groups) > 4:
            old_scope, _ = self.groups.popitem(last=False)
            self.close_connection(self.connections.pop(old_scope, None))
        cache, cookies = self.groups[scope]
        cache.begin_job()
        return cache, cookies

    def remember_cookies(self, scope, cookies):
        if scope in self.groups:
            cache, _ = self.groups[scope]
            self.groups[scope] = (cache, cookies)

    @staticmethod
    def close_connection(fetcher):
        if fetcher is not None and fetcher.requests_session is not None:
            fetcher.requests_session.close()
            fetcher.requests_session = None

    def connect(self, scope, config):
        fetcher = config.get_fetcher()
        if type(fetcher) not in {RequestsFetcher, CloudScraperFetcher}:
            return  # Browser/proxy-specific fetchers retain upstream behavior.
        previous = self.connections.pop(scope, None)
        if previous is not None and type(previous) is type(fetcher):
            # Transfer ownership: the old fetcher's destructor must not close
            # a session now used by a new configuration and progress callback.
            fetcher.requests_session = previous.requests_session
            previous.requests_session = None
            fetcher.set_cookiejar(config.get_cookiejar())
        else:
            self.close_connection(previous)
        self.connections[scope] = fetcher

    def word_count(self, digest):
        if digest in self.word_counts:
            self.word_counts.move_to_end(digest)
            return self.word_counts[digest]
        return None

    def remember_word_count(self, digest, count):
        self.word_counts[digest] = str(count)
        self.word_counts.move_to_end(digest)
        while len(self.word_counts) > 128:
            self.word_counts.popitem(last=False)

    def close(self):
        for fetcher in self.connections.values():
            self.close_connection(fetcher)
        self.connections.clear()
        self.groups.clear()
        self.previews.clear()
        self.word_counts.clear()

    def preview(self, scope, source):
        key = (scope, source)
        entry = self.previews.get(key)
        if entry and self.clock() - entry[0] < TTL:
            self.previews.move_to_end(key)
            return dict(entry[1])
        self.previews.pop(key, None)
        return None

    def remember_preview(self, scope, source, metadata):
        key = (scope, source)
        self.previews[key] = (self.clock(), dict(metadata))
        self.previews.move_to_end(key)
        while len(self.previews) > 100:
            self.previews.popitem(last=False)
