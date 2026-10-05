from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import zipfile

import pytest
from fanficfare.epubutils import get_dcsource_chaptercount

from fanficfare_gui.engine import execute, parse_urls, safe_name


def request(tmp_path, operation="download", source="http://test1.com?sid=1[1-2]", fmt="epub"):
    return {"operation": operation, "source": source, "format": fmt, "output": str(tmp_path)}


def test_links_keep_ranges_and_order():
    assert parse_urls("# comment\nhttps://a.example/1[2-4]\nhttps://b.example/2\nhttps://a.example/1[2-4]") == ["https://a.example/1[2-4]", "https://b.example/2"]
    with pytest.raises(ValueError):
        parse_urls("https://a.example/1 https://b.example/2")
    assert safe_name("CON") == "_CON"
    assert "/" not in safe_name("A/B")


@pytest.mark.parametrize("fmt", ["epub", "txt", "html", "mobi"])
def test_real_engine_downloads_formats(tmp_path, fmt):
    result = execute(request(tmp_path, fmt=fmt))
    saved = Path(result["path"])
    assert saved.is_file() and saved.stat().st_size > 100
    assert not list(tmp_path.glob(".fff-*"))
    if fmt in ("epub", "html"):
        with zipfile.ZipFile(saved) as archive:
            assert archive.testzip() is None
    if fmt == "epub":
        assert get_dcsource_chaptercount(str(saved))[1] == 2


def test_preview_creates_no_book(tmp_path):
    result = execute(request(tmp_path, "preview"))
    assert result["metadata"]["title"]
    assert list(tmp_path.iterdir()) == []


def test_repeated_download_never_overwrites(tmp_path):
    first = execute(request(tmp_path))
    before = Path(first["path"]).read_bytes()
    second = execute(request(tmp_path))
    assert first["path"] != second["path"]
    assert Path(first["path"]).read_bytes() == before


def test_update_preserves_original_backup_and_reuses_chapters(tmp_path):
    initial = execute(request(tmp_path))
    book = Path(initial["path"])
    original = book.read_bytes()
    result = execute(request(tmp_path, "update", str(book)))
    assert result["status"] == "done"
    assert Path(result["backup"]).read_bytes() == original
    assert get_dcsource_chaptercount(str(book))[1] > 2
    with zipfile.ZipFile(book) as updated, zipfile.ZipFile(result["backup"]) as backup:
        assert updated.read("OEBPS/file0001.xhtml") == backup.read("OEBPS/file0001.xhtml")
    up_to_date = execute(request(tmp_path, "update", str(book)))
    assert up_to_date["status"] == "unchanged"
    assert len(list((tmp_path / "FanFicFare Backups").iterdir())) == 1


def test_failed_update_does_not_change_original(tmp_path, monkeypatch):
    initial = execute(request(tmp_path))
    book = Path(initial["path"])
    original = hashlib.sha256(book.read_bytes()).hexdigest()
    def fail(*args):
        raise ValueError("Forced integrity failure")
    monkeypatch.setattr("fanficfare_gui.engine.validate_output", fail)
    with pytest.raises(ValueError, match="Forced integrity"):
        execute(request(tmp_path, "update", str(book)))
    assert hashlib.sha256(book.read_bytes()).hexdigest() == original
    assert not (tmp_path / "FanFicFare Backups").exists()


@pytest.mark.parametrize("source", ["http://test1.com?sid=666", "http://test1.com?sid=667", "http://test1.com?sid=668", "https://unsupported.example/story"])
def test_errors_leave_no_download(tmp_path, source):
    with pytest.raises(Exception):
        execute(request(tmp_path, source=source))
    assert list(tmp_path.iterdir()) == []


def test_extract_only_returns_links(tmp_path):
    result = execute(request(tmp_path, "extract", "http://test1.com/series"))
    assert len(result["urls"]) == 9
    assert list(tmp_path.iterdir()) == []


def test_worker_returns_machine_readable_failure(tmp_path):
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run([sys.executable, "-m", "fanficfare_gui", "--worker"], input=json.dumps(request(tmp_path, source="http://test1.com?sid=666")) + "\n", text=True, capture_output=True, env=environment, timeout=30)
    assert result.returncode == 1
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1]["type"] == "error"
