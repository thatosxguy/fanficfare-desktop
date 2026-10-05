"""One independently cancellable, persistent process in the desktop queue."""

import json
import os
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QElapsedTimer, QProcess, QProcessEnvironment, QTimer


class QueueWorker:
    def __init__(self, window):
        self.window = window
        self.process = None
        self.active = None
        self.work = None
        self.buffer = b""
        self.pending = None
        self.result_received = False
        self.cancelled = False
        self.finalizing = False
        self.percent = None
        self.message = "Starting story job…"
        self.elapsed = QElapsedTimer()

    def start(self, row):
        self.active = row
        self.buffer = b""
        self.result_received = self.cancelled = self.finalizing = False
        self.percent = None
        self.message = "Starting story job…"
        self.elapsed.start()
        job = self.window.jobs[row]
        job.status = "Running"
        self.window.refresh(row)
        try:
            directory = Path(job.request["source"]).expanduser().resolve().parent if job.request["operation"] == "update" else Path(job.request["output"]).expanduser()
            directory.mkdir(parents=True, exist_ok=True)
            self.work = tempfile.TemporaryDirectory(prefix=".fff-work-", dir=directory)
            self.pending = dict(job.request, work_dir=self.work.name, pacing_db=self.window.pacing_db)
            if self.process and self.process.state() == QProcess.ProcessState.Running:
                self.send()
                return
            process = self.process = QProcess(self.window)
            environment = QProcessEnvironment.systemEnvironment()
            package_root = str(Path(__file__).resolve().parent.parent)
            environment.insert("PYTHONPATH", package_root + os.pathsep + environment.value("PYTHONPATH", ""))
            environment.insert("PYTHONUNBUFFERED", "1")
            environment.insert("PYTHONIOENCODING", "utf-8")
            process.setProcessEnvironment(environment)
            process.readyReadStandardOutput.connect(self.read_events)
            process.readyReadStandardError.connect(lambda: process.readAllStandardError())
            process.finished.connect(self.finished)
            process.errorOccurred.connect(self.process_error)
            process.started.connect(self.send)
            arguments = ["--worker"] if getattr(sys, "frozen", False) else ["-m", "fanficfare_gui", "--worker"]
            process.start(sys.executable, arguments)
        except OSError as error:
            job.error = str(error)
            self.complete(1)

    def send(self):
        if self.process and self.pending is not None:
            self.process.write((json.dumps(self.pending) + "\n").encode("utf-8"))
            self.pending = None

    def read_events(self):
        if not self.process:
            return
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            self.window.handle_event(self, event)

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.active is not None:
            self.window.jobs[self.active].error = "Could not start the FanFicFare worker. Check the application installation."
            self.finished(1)

    def finished(self, code, _status=None):
        self.read_events()
        if self.process:
            self.process.deleteLater()
            self.process = None
        self.complete(code)

    def complete(self, code=0):
        if self.active is None:
            return
        row = self.active
        job = self.window.jobs[row]
        if not self.result_received:
            job.status = "Cancelled" if self.cancelled else "Failed"
            if not self.cancelled and not job.error:
                job.error = f"The download process ended without a result (exit {code})."
        if self.work:
            self.work.cleanup()
            self.work = None
        self.pending = None
        self.active = None
        self.finalizing = False
        self.window.refresh(row)
        self.window.tick_activity()
        if not self.window.closing:
            QTimer.singleShot(0, self.window.next_job)

    def cancel(self):
        if self.process and self.active is not None and not self.finalizing:
            self.cancelled = True
            self.process.kill()

    def shutdown(self):
        process = self.process
        if process:
            if self.active is not None:
                self.cancel()
            else:
                process.closeWriteChannel()
            if not process.waitForFinished(3000):
                process.kill()
                process.waitForFinished(3000)
