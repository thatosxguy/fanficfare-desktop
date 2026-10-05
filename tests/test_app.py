from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox
import pytest

from fanficfare_gui.app import Window


@pytest.fixture(autouse=True)
def allow_test_window_cleanup(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)


def window(qtbot, tmp_path):
    widget = Window(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    widget.output.setText(str(tmp_path / "books"))
    qtbot.addWidget(widget)
    return widget


def slow_chapters(widget, tmp_path):
    ini = tmp_path / "slow.ini"
    ini.write_text("[test1.com]\nslow_down_sleep_time:2\n")
    widget.ini.setText(str(ini))


def test_queue_runs_real_worker_and_reports_failures(qtbot, tmp_path):
    widget = window(qtbot, tmp_path)
    widget.urls.setPlainText("http://test1.com?sid=1[1-2]\nhttp://test1.com?sid=666")
    widget.add_urls()
    widget.start_queue()
    qtbot.waitUntil(lambda: not widget.running, timeout=30000)
    assert [job.status for job in widget.jobs] == ["Done", "Failed"]
    assert Path(widget.jobs[0].result["path"]).is_file()
    assert widget.jobs[1].error
    assert not list((tmp_path / "books").glob(".fff-*"))


def test_cancellation_cleans_staging_and_keeps_remaining_queue(qtbot, tmp_path):
    widget = window(qtbot, tmp_path)
    slow_chapters(widget, tmp_path)
    widget.urls.setPlainText("http://test1.com?sid=670\nhttp://test1.com?sid=672[1-2]\nhttp://test1.com?sid=1[1-2]")
    widget.add_urls()
    widget.start_queue()
    qtbot.waitUntil(lambda: bool(widget.jobs[0].metadata), timeout=10000)
    widget.table.selectRow(0)
    widget.cancel_current()
    qtbot.waitUntil(lambda: widget.active is None, timeout=10000)
    assert [job.status for job in widget.jobs] == ["Cancelled", "Done", "Queued"]
    assert len(list((tmp_path / "books").iterdir())) == 1
    assert not list((tmp_path / "books").glob(".fff-*"))
    widget.start_queue()
    qtbot.waitUntil(lambda: not widget.running, timeout=15000)
    assert widget.jobs[2].status == "Done"


def test_extract_populates_input_for_review(qtbot, tmp_path):
    widget = window(qtbot, tmp_path)
    widget.enqueue([widget.request("extract", "http://test1.com/series")])
    widget.start_queue()
    qtbot.waitUntil(lambda: not widget.running, timeout=10000)
    assert len(widget.urls.toPlainText().splitlines()) == 9
    assert len(widget.jobs) == 1


def test_repeated_previews_reuse_worker_and_metadata(qtbot, tmp_path):
    widget = window(qtbot, tmp_path)
    request = widget.request("preview", "http://test1.com?sid=1")
    widget.enqueue([request])
    widget.start_queue()
    qtbot.waitUntil(lambda: not widget.running, timeout=10000)
    process = widget.process
    pid = process.processId()
    widget.enqueue([request])
    widget.start_queue()
    qtbot.waitUntil(lambda: not widget.running, timeout=10000)
    assert widget.process.processId() == pid
    assert widget.jobs[1].result["cached"] is True
    assert widget.table.item(1, 1).text() == "123,456"
    assert "Words:" in widget.details.toPlainText()


def test_page_activity_shows_busy_progress_and_elapsed_time(qtbot, tmp_path):
    widget = window(qtbot, tmp_path)
    widget.enqueue([widget.request("preview", "http://test1.com?sid=1")])
    worker = widget.workers[0]
    worker.active = 0
    worker.elapsed.start()
    widget.handle_event(worker, {"type": "activity", "percent": None, "message": "Loading page 2 from www.literotica.com…"})
    assert widget.progress.minimum() == widget.progress.maximum() == 0
    assert "Loading page 2" in widget.message.text()
    assert "elapsed" in widget.message.text()
    worker.active = None


def test_two_jobs_run_together_and_third_waits(qtbot, tmp_path):
    widget = window(qtbot, tmp_path)
    slow_chapters(widget, tmp_path)
    widget.enqueue([widget.request("download", url) for url in (
        "http://test1.com?sid=670[1-2]", "http://test1.com?sid=672[1-2]", "http://test1.com?sid=1[1-2]")])
    widget.start_queue()
    qtbot.waitUntil(lambda: all(job.metadata for job in widget.jobs[:2]), timeout=10000)
    assert [job.status for job in widget.jobs] == ["Running", "Running", "Queued"]
    assert len({w.process.processId() for w in widget.workers}) == 2
    widget.table.selectRow(1)
    assert widget.selected_worker().active == 1
    qtbot.waitUntil(lambda: not widget.running, timeout=15000)
    assert all(job.status == "Done" for job in widget.jobs)


def test_same_source_jobs_stay_serial_and_reuse_preview(qtbot, tmp_path):
    widget = window(qtbot, tmp_path)
    request = widget.request("preview", "http://test1.com?sid=1")
    widget.enqueue([request, request])
    widget.start_queue()
    qtbot.waitUntil(lambda: not widget.running, timeout=10000)
    assert widget.jobs[1].result["cached"] is True
    assert widget.workers[1].process is None


def test_metadata_update_keeps_other_row_items(qtbot, tmp_path):
    widget = window(qtbot, tmp_path)
    widget.enqueue([widget.request("preview", f"http://test1.com?sid={i}") for i in range(200)])
    untouched = widget.table.item(199, 0)
    worker = widget.workers[0]
    worker.active = 0
    worker.elapsed.start()
    widget.handle_event(worker, {"type": "metadata", "metadata": {"title": "Updated title", "numWords": "100"}})
    assert widget.table.item(199, 0) is untouched
    assert widget.table.item(0, 0).text() == "Updated title"
    worker.active = None
