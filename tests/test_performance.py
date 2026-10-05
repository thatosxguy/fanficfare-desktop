from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

from bs4 import BeautifulSoup
import pytest

from fanficfare_gui.engine import configuration, execute, html_word_count
from fanficfare_gui.network import SitePacer, attach_pacing, initialize_pacing
from fanficfare_gui.session import RecentPages, Session


def test_real_http_connection_survives_configuration_changes(tmp_path):
    peers = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            peers.append(self.client_address)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = Session()
    transports = []
    try:
        for index in range(2):
            config = configuration("http://test1.com?sid=1", "epub")
            config.set("overrides", "http_proxy", "")
            config.set("overrides", "connect_timeout", "3")
            scope = session.scope({}, config)
            cache, cookies = session.pages(scope)
            config.set_basic_cache(cache)
            if cookies is not None:
                config.set_cookiejar(cookies)
            session.connect(scope, config)
            fetcher = config.get_fetcher()
            url = f"http://127.0.0.1:{server.server_port}/{index}"
            assert fetcher.get_request_redirected(url)[0] == b"OK"
            transports.append(fetcher.requests_session)
            session.remember_cookies(scope, config.get_cookiejar())
        assert transports[0] is transports[1]
        assert peers[0] == peers[1]  # Same TCP source port, not just same object.
    finally:
        session.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_site_pacing_reservations_are_shared_and_sites_independent(tmp_path):
    path = str(tmp_path / "pacing.sqlite")
    initialize_pacing(path)
    sleeps = []
    first = SitePacer(path, clock=lambda: 100, sleep=sleeps.append)
    second = SitePacer(path, clock=lambda: 100, sleep=sleeps.append)
    first.wait("literotica.com", 2, lambda event: None)
    second.wait("literotica.com", 2, lambda event: None)
    second.wait("other.example", 2, lambda event: None)
    assert sleeps == [2]
    second.wait("literotica.com", 0, lambda event: None)
    assert sleeps == [2, 4]  # A faster job cannot erase an existing delay.


def test_pacing_database_handles_close_before_folder_cleanup(tmp_path, monkeypatch):
    import sqlite3
    from fanficfare_gui import network
    original = sqlite3.connect
    connections = []
    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        connections.append(connection)
        return connection
    monkeypatch.setattr(network.sqlite3, "connect", connect)
    path = tmp_path / "pacing.sqlite"
    initialize_pacing(str(path))
    SitePacer(str(path), clock=lambda: 100, sleep=lambda delay: None).wait("same.example", 3, lambda event: None)
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    # Windows forbids deleting a SQLite file while a connection is open.
    path.unlink()
    assert not path.exists()


def test_simultaneous_pacing_reservations_do_not_collide(tmp_path):
    path = str(tmp_path / "pacing.sqlite")
    initialize_pacing(path)
    barrier = threading.Barrier(2)

    def reserve(_):
        waits = []
        barrier.wait(timeout=3)
        SitePacer(path, clock=lambda: 100, sleep=waits.append).wait("same.example", 3, lambda event: None)
        return waits

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert sorted(results) == [[], [3]]


def test_pacing_is_shared_between_processes(tmp_path):
    import os
    import subprocess
    import sys
    path = str(tmp_path / "pacing.sqlite")
    initialize_pacing(path)
    code = "from fanficfare_gui.network import SitePacer; import sys; waits=[]; SitePacer(sys.argv[1], clock=lambda:100, sleep=waits.append).wait('same.example',3,lambda e:None); print(waits)"
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    processes = [subprocess.Popen([sys.executable, "-c", code, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment) for _ in range(2)]
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        results.append(stdout.strip())
    assert sorted(results) == ["[3.0]", "[]"]


def test_cached_page_does_not_reserve_pacing(tmp_path, monkeypatch):
    path = str(tmp_path / "pacing.sqlite")
    initialize_pacing(path)
    config = configuration("http://test1.com?sid=1", "epub")
    config.set("overrides", "use_basic_cache", "true")
    cache = RecentPages()
    config.set_basic_cache(cache)
    cache.set_to_cache("https://test1.com/cached", b"cached", "https://test1.com/cached")
    monkeypatch.setattr(SitePacer, "wait", lambda *args: pytest.fail("Cache hit consumed a request slot"))
    attach_pacing(config, path, lambda event: None)
    assert config.get_fetcher().get_request_redirected("https://test1.com/cached")[0] == b"cached"


@pytest.mark.parametrize("html", [
    "<p>One <b>two</b> three</p><script>ignored words</script><style>also ignored</style>",
    "<p>Café &amp; tea; don't stop—rock-and-roll isn’t dead. 中文 123</p><!-- ignored -->",
    "<div>first<br/>second &nbsp; third</div><p>fourth</p>",
    "<p>broken <b>markup<p>still text",
    "<p>A &lt; B &gt; C &quot;quoted&quot;</p><script>let x = '<div>'; ignore()</script>",
    "<script src='empty'/><p>Words remain</p>",
])
def test_streaming_word_count_matches_previous_count(html):
    import re
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style"]):
        element.decompose()
    expected = len(re.findall(r"\b\w+(?:['’\-]\w+)*\b", soup.get_text(" ", strip=True)))
    assert html_word_count([html]) == expected


def test_unchanged_epub_avoids_reparse_but_changed_bytes_invalidate(tmp_path, monkeypatch):
    import fanficfare_gui.engine as engine
    request = {"operation": "download", "source": "http://test1.com?sid=674", "format": "epub", "output": str(tmp_path)}
    session = Session()
    result = execute(request, session=session)
    book = Path(result["path"])
    original_get_update = engine.get_update_data
    reads = []

    def read(*args, **kwargs):
        reads.append(args[0])
        return original_get_update(*args, **kwargs)

    monkeypatch.setattr(engine, "get_update_data", read)
    update = dict(request, operation="update", source=str(book))
    assert execute(update, session=session)["metadata"]["numWords"] == result["metadata"]["numWords"]
    assert reads == []
    import zipfile
    with zipfile.ZipFile(book, "a") as archive:
        archive.comment = b"Changed book fingerprint"
    assert execute(update, session=session)["status"] == "unchanged"
    assert reads == [str(book)]
    assert execute(update, session=session)["status"] == "unchanged"
    assert len(reads) == 1
    session.close()


def test_story_specific_settings_do_not_share_connection_scope(tmp_path):
    config = configuration("http://test1.com?sid=1", "epub")
    config.add_section("http://test1.com?sid=2")
    config.addUrlConfigSection("http://test1.com?sid=1")
    session = Session()
    ordinary = session.scope({}, config)
    config.addUrlConfigSection("http://test1.com?sid=2")
    assert session.scope({}, config) != ordinary
