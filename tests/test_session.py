from pathlib import Path

import pytest
from fanficfare.adapters.adapter_test1 import TestSiteAdapter as FixtureAdapter
from fanficfare.fetchers.base_fetcher import FetcherResponse
from fanficfare.fetchers.fetcher_requests import RequestsFetcher

from fanficfare_gui.theme import ASSETS
from fanficfare_gui.engine import execute
from fanficfare_gui.session import RecentPages, Session, TTL


@pytest.fixture
def metadata_requests(tmp_path, monkeypatch):
    ini = tmp_path / "test.ini"
    ini.write_text("[test1.com]\nuse_basic_cache:true\nslow_down_sleep_time:0\ninclude_images:true\n")
    calls = []
    original = FixtureAdapter.extractChapterUrlsAndMetadata
    def extract(adapter):
        adapter.get_request("https://metadata.example/story")
        original(adapter)
        adapter.setCoverImage(adapter.url, "https://metadata.example/cover.png")
    def transport(fetcher, method, url, **kwargs):
        calls.append(url)
        data = (ASSETS / "app-icon.png").read_bytes() if url.endswith(".png") else b"<html>metadata</html>"
        return FetcherResponse(data, redirecturl=url)
    monkeypatch.setattr(FixtureAdapter, "extractChapterUrlsAndMetadata", extract)
    monkeypatch.setattr(RequestsFetcher, "request", transport)
    return ini, calls


def test_preview_skips_images_and_download_reuses_metadata_pages(tmp_path, metadata_requests):
    ini, calls = metadata_requests
    session = Session()
    request = {"operation": "preview", "source": "http://test1.com?sid=1[1-2]", "format": "epub", "ini": str(ini), "output": str(tmp_path)}
    events = []
    execute(request, events.append, session)
    assert calls == ["https://metadata.example/story"]
    assert any(event["type"] == "activity" and "Loading page" in event["message"] for event in events)
    assert execute(request, session=session)["cached"] is True
    assert len(calls) == 1
    result = execute(dict(request, operation="download"), session=session)
    assert Path(result["path"]).is_file()
    assert calls == ["https://metadata.example/story", "https://metadata.example/cover.png"]


def test_expiry_and_ini_changes_trigger_fresh_metadata(tmp_path, metadata_requests):
    ini, calls = metadata_requests
    now = [1000.0]
    session = Session(clock=lambda: now[0])
    request = {"operation": "preview", "source": "http://test1.com?sid=1", "format": "epub", "ini": str(ini)}
    execute(request, session=session)
    now[0] += TTL + 1
    execute(request, session=session)
    assert len(calls) == 2
    ini.write_text(ini.read_text() + "clean_chapter_titles:false\n")
    execute(request, session=session)
    assert len(calls) == 3


def test_cache_keeps_metadata_only_between_jobs():
    cache = RecentPages()
    cache.set_to_cache("meta", b"metadata", "meta")
    cache.capture_metadata = False
    cache.set_to_cache("chapter", b"chapter", "chapter")
    cache.begin_job()
    assert cache.has_cachekey("meta")
    assert not cache.has_cachekey("chapter")


def test_missing_word_count_is_calculated_and_included_in_book(tmp_path):
    import zipfile
    result = execute({"operation": "download", "source": "http://test1.com?sid=674[1-2]", "format": "epub", "output": str(tmp_path)})
    metadata = result["metadata"]
    assert metadata["wordCountSource"] == "calculated"
    assert int(metadata["numWords"].replace(",", "")) > 100
    with zipfile.ZipFile(result["path"]) as book:
        assert metadata["numWords"].encode() in book.read("OEBPS/title_page.xhtml")


def test_up_to_date_book_still_has_word_count_without_rewrite(tmp_path):
    request = {"operation": "download", "source": "http://test1.com?sid=674", "format": "epub", "output": str(tmp_path)}
    downloaded = execute(request)
    book = Path(downloaded["path"])
    original = book.read_bytes()
    updated = execute(dict(request, operation="update", source=str(book)))
    assert updated["status"] == "unchanged"
    assert updated["metadata"]["wordCountSource"] == "calculated"
    assert int(updated["metadata"]["numWords"].replace(",", "")) > 100
    assert book.read_bytes() == original
