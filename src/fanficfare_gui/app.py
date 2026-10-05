from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .engine import parse_urls
from .network import initialize_pacing
from .queue_worker import QueueWorker
from .theme import ASSETS, apply_theme, display_words


@dataclass
class Job:
    request: dict
    status: str = "Queued"
    metadata: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    error: str = ""


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(True)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    if primary:
        widget.setObjectName("primary")
    return widget


class Window(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or QSettings("FanFicFare Desktop", "FanFicFare Desktop")
        self.jobs = []
        self.workers = [QueueWorker(self) for _ in range(2)]
        self.affinity = {}
        self.rendered_rows = {}
        self.running = False
        self.closing = False
        self.network_work = tempfile.TemporaryDirectory(prefix="fff-network-")
        self.pacing_db = str(Path(self.network_work.name) / "pacing.sqlite")
        initialize_pacing(self.pacing_db)
        self.activity_timer = QTimer(self)
        self.activity_timer.setInterval(1000)
        self.activity_timer.timeout.connect(self.tick_activity)
        self.setWindowTitle("FanFicFare Desktop")
        self.setWindowIcon(QIcon(str(ASSETS / "app-icon.svg")))
        self.resize(1280, 860)
        self.setMinimumSize(1050, 760)
        self.build_ui()
        self.restore_settings()
        self.refresh()

    def build_ui(self):
        root = QWidget()
        root.setObjectName("page")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(32, 24, 32, 22)
        layout.setSpacing(18)

        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QPixmap(str(ASSETS / "app-icon.svg")).scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        icon.setAccessibleName("Open book")
        header.addWidget(icon)
        name = QVBoxLayout()
        name.setSpacing(0)
        name.addWidget(label("FanFicFare", "appName"))
        name.addWidget(label("Desktop", "caption"))
        header.addLayout(name)
        header.addStretch()
        supported = button("Supported sites ↗", lambda: QDesktopServices.openUrl(QUrl("https://github.com/JimmXinu/FanFicFare/wiki/SupportedSites")))
        supported.setObjectName("quiet")
        header.addWidget(supported)
        help_button = button("Help ↗", lambda: QDesktopServices.openUrl(QUrl("https://github.com/JimmXinu/FanFicFare/wiki")))
        help_button.setObjectName("quiet")
        header.addWidget(help_button)
        layout.addLayout(header)

        hero = QVBoxLayout()
        hero.setSpacing(4)
        hero.addWidget(label("Stories worth keeping.", "heading"))
        hero.addWidget(label("Save your favorite web stories as ebooks, and keep them up to date.", "muted"))
        layout.addLayout(hero)

        composer = QHBoxLayout()
        composer.setSpacing(18)
        links = QFrame()
        links.setObjectName("panel")
        form = QVBoxLayout(links)
        form.setContentsMargins(20, 18, 20, 18)
        form.setSpacing(12)
        form.addWidget(label("Add a story", "sectionTitle"))
        self.urls = QPlainTextEdit()
        self.urls.setObjectName("storyLinks")
        self.urls.setPlaceholderText("Paste story links here, one per line.\nhttps://…/your-favorite-story")
        self.urls.setFixedHeight(104)
        self.urls.setAccessibleName("Story links, one per line")
        form.addWidget(self.urls, 1)
        form.addWidget(label("Want just a few chapters? Add [1-5] to the end of a story link.", "caption"))
        actions = QHBoxLayout()
        import_button = button("Import links…", self.import_urls)
        import_button.setObjectName("quiet")
        actions.addWidget(import_button)
        extract_button = button("Find links on a page…", self.extract)
        extract_button.setObjectName("quiet")
        actions.addWidget(extract_button)
        actions.addStretch()
        self.preview_button = button("Preview", lambda: self.add_urls("preview"))
        self.add_button = button("Add to queue", self.add_urls, True)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.add_button)
        form.addLayout(actions)
        def update_link_actions():
            enabled = bool(self.urls.toPlainText().strip())
            self.preview_button.setEnabled(enabled)
            self.add_button.setEnabled(enabled)
        self.urls.textChanged.connect(update_link_actions)
        update_link_actions()
        composer.addWidget(links, 1)

        settings = QFrame()
        settings.setObjectName("panel")
        settings.setFixedWidth(310)
        options = QVBoxLayout(settings)
        options.setContentsMargins(18, 16, 18, 16)
        options.setSpacing(8)
        options.addWidget(label("Download preferences", "sectionTitle"))
        format_row = QHBoxLayout()
        format_row.addWidget(label("File format", "fieldLabel"))
        format_row.addStretch()
        self.format = QComboBox()
        self.format.addItems(["EPUB", "HTML", "TXT", "MOBI"])
        self.format.setAccessibleName("Ebook format")
        self.format.setToolTip("HTML is saved as a ZIP with its supporting files.")
        format_row.addWidget(self.format)
        options.addLayout(format_row)
        destination_label = QHBoxLayout()
        destination_label.addWidget(label("Save to", "fieldLabel"))
        destination_label.addStretch()
        choose = button("Change…", self.choose_output)
        choose.setObjectName("inline")
        destination_label.addWidget(choose)
        options.addLayout(destination_label)
        self.output = QLineEdit()
        self.output.setReadOnly(True)
        self.output.setAccessibleName("Download destination")
        options.addWidget(self.output)
        self.adult = QCheckBox("Allow adult content")
        self.adult.setToolTip("Confirm that you meet the source site's age requirements.")
        options.addWidget(self.adult)

        self.site_settings = QDialog(self)
        self.site_settings.setWindowTitle("Site settings and login")
        self.site_settings.resize(520, 240)
        self.site_settings_toggle = button("Site settings and login…", self.site_settings.open)
        self.site_settings_toggle.setObjectName("inline")
        options.addWidget(self.site_settings_toggle)
        config = QVBoxLayout(self.site_settings)
        config.setContentsMargins(24, 24, 24, 24)
        config.setSpacing(12)
        config.addWidget(label("Site settings and login", "sectionTitle"))
        config.addWidget(label("Choose a personal.ini file for site logins and custom preferences. This is optional.", "muted"))
        self.ini = QLineEdit()
        self.ini.setReadOnly(True)
        self.ini.setAccessibleName("Selected personal.ini configuration")
        self.ini.setPlaceholderText("Optional personal.ini")
        config.addWidget(self.ini)
        config_buttons = QHBoxLayout()
        config_buttons.addWidget(button("Choose file…", self.choose_ini))
        clear_ini = button("Clear", lambda: self.ini.clear())
        clear_ini.setObjectName("quiet")
        config_buttons.addWidget(clear_ini)
        config.addLayout(config_buttons)
        close_settings = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_settings.rejected.connect(self.site_settings.reject)
        config.addWidget(close_settings)
        def update_site_settings():
            self.site_settings_toggle.setText("Site settings · configured" if self.ini.text() else "Site settings and login…")
            self.site_settings_toggle.setToolTip(self.ini.text() or "Optional site logins and custom preferences")
        self.ini.textChanged.connect(update_site_settings)
        options.addStretch()
        composer.addWidget(settings)
        layout.addLayout(composer)

        queue_header = QHBoxLayout()
        queue_header.addWidget(label("Download queue", "sectionTitle"))
        self.queue_count = label("No stories yet", "badge")
        queue_header.addWidget(self.queue_count)
        queue_header.addStretch()
        update_button = button("Update existing EPUBs…", self.update_epubs)
        update_button.setObjectName("quiet")
        queue_header.addWidget(update_button)
        open_folder = button("Open download folder ↗", self.open_folder)
        open_folder.setObjectName("quiet")
        queue_header.addWidget(open_folder)
        layout.addLayout(queue_header)

        queue = QFrame()
        queue.setObjectName("panel")
        queue_layout = QVBoxLayout(queue)
        queue_layout.setContentsMargins(14, 8, 14, 14)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Story", "Words", "Action", "Format", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, 90 if column < 4 else 125)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setAccessibleName("Story download queue")
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.empty_state = QWidget(self.table.viewport())
        empty = QVBoxLayout(self.empty_state)
        empty.setContentsMargins(16, 20, 16, 20)
        empty.setSpacing(8)
        empty.addStretch()
        empty_title = label("Your next read starts here", "sectionTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(empty_title)
        empty_hint = label("Add a story link above. Your previews and downloads will appear here.", "muted")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(empty_hint)
        empty.addStretch()
        viewport_layout = QVBoxLayout(self.table.viewport())
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        viewport_layout.addWidget(self.empty_state)
        splitter.addWidget(self.table)
        detail = QWidget()
        panel = QVBoxLayout(detail)
        panel.setContentsMargins(18, 12, 8, 0)
        panel.setSpacing(12)
        panel.addWidget(label("Story details", "fieldLabel"))
        self.details = QPlainTextEdit()
        self.details.setObjectName("storyDetails")
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a story to see its author, word count, progress, and saved book.")
        panel.addWidget(self.details)
        self.open_book = button("Open saved book ↗", self.open_selected)
        panel.addWidget(self.open_book)
        splitter.addWidget(detail)
        splitter.setSizes([840, 280])
        splitter.setChildrenCollapsible(False)
        queue_layout.addWidget(splitter)
        layout.addWidget(queue, 1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.message = label("Add a story to get started.", "muted")
        footer.addWidget(self.message, 1)
        self.remove_button = button("Remove", self.remove_selected)
        self.clear_button = button("Clear finished", self.clear_finished)
        self.retry_button = button("Retry", self.retry_selected)
        for action in (self.remove_button, self.clear_button, self.retry_button):
            action.setObjectName("quiet")
            footer.addWidget(action)
        self.cancel_button = button("Cancel selected", self.cancel_current)
        self.start_button = button("Start queue", self.start_queue, True)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.start_button)
        layout.addLayout(footer)
        attribution = label(f"Powered by FanFicFare {version('FanFicFare')} · Independent desktop app", "caption")
        attribution.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(attribution)
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)

    def restore_settings(self):
        default = str(Path.home() / "Downloads" / "FanFicFare")
        self.output.setText(self.settings.value("output", default))
        self.ini.setText(self.settings.value("ini", ""))
        self.format.setCurrentText(self.settings.value("format", "EPUB"))

    def save_settings(self):
        for name in ("output", "ini"):
            self.settings.setValue(name, getattr(self, name).text())
        self.settings.setValue("format", self.format.currentText())

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "Save books to", self.output.text())
        if path:
            self.output.setText(path)

    def choose_ini(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select personal.ini", "", "INI files (*.ini);;All files (*)")
        if path:
            self.ini.setText(path)

    def open_folder(self):
        path = Path(self.output.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def request(self, operation, source):
        return {"operation": operation, "source": source, "format": self.format.currentText().lower(),
                "output": self.output.text(), "ini": self.ini.text() or None, "adult": self.adult.isChecked()}

    def enqueue(self, requests):
        for request in requests:
            self.jobs.append(Job(request))
        self.save_settings()
        self.refresh()
        if self.running:
            self.next_job()

    def add_urls(self, operation="download"):
        # QPushButton's clicked(bool) may supply a checked state.
        if not isinstance(operation, str):
            operation = "download"
        try:
            urls = parse_urls(self.urls.toPlainText())
        except ValueError as error:
            QMessageBox.warning(self, "Check your links", str(error))
            return
        self.enqueue([self.request(operation, url) for url in urls])
        self.urls.clear()
        self.message.setText(f"Added {len(urls)} {'preview' if operation == 'preview' else 'download'} job(s).")

    def import_urls(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import story links", "", "Text files (*.txt);;All files (*)")
        if path:
            try:
                self.urls.setPlainText(Path(path).read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError) as error:
                QMessageBox.warning(self, "Cannot import links", str(error))

    def extract(self):
        source, ok = QInputDialog.getText(self, "Find story links", "Page or series URL:")
        if ok:
            try:
                urls = parse_urls(source)
                self.enqueue([self.request("extract", urls[0])])
            except ValueError as error:
                QMessageBox.warning(self, "Check the page URL", str(error))

    def update_epubs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Update existing EPUBs", self.output.text(), "EPUB books (*.epub)")
        requests = []
        for path in paths:
            request = self.request("update", path)
            request["format"] = "epub"
            requests.append(request)
        self.enqueue(requests)

    @property
    def active(self):
        return next((worker.active for worker in self.workers if worker.active is not None), None)

    @property
    def process(self):
        return self.workers[0].process

    def selected_worker(self):
        row = self.table.currentRow()
        return next((worker for worker in self.workers if worker.active == row), None)

    def refresh(self, row=None):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.jobs))
        self.empty_state.setVisible(not self.jobs)
        self.table.horizontalHeader().setVisible(bool(self.jobs))
        active_count = sum(worker.active is not None for worker in self.workers)
        total = len(self.jobs)
        self.queue_count.setText(f"{total} {'story' if total == 1 else 'stories'}" + (f" · {active_count} active" if active_count else "") if total else "No stories yet")
        rows = range(len(self.jobs)) if row is None else [row]
        for index in rows:
            job = self.jobs[index]
            name = job.metadata.get("title") or job.request["source"]
            worker = next((w for w in self.workers if w.active == index), None)
            status = job.status
            if status == "Running" and worker and worker.percent is not None:
                status += f" · {worker.percent}%"
            values = (name, display_words(job.metadata), job.request["operation"].title(), job.request["format"].upper(), status)
            word_tip = "Calculated from downloaded text" if job.metadata.get("wordCountSource") == "calculated" else "Reported by the source site" if job.metadata.get("numWords") else "Not reported by the source; calculated after download"
            tip = job.error or job.request["source"]
            state = (values, tip, word_tip)
            if self.rendered_rows.get(index) == state:
                continue
            self.rendered_rows[index] = state
            for column, value in enumerate(values):
                item = self.table.item(index, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(index, column, item)
                if item.text() != value:
                    item.setText(value)
                item.setToolTip(word_tip if column == 1 else tip)
                if column == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setRowHeight(index, 42)
        self.table.blockSignals(False)
        self.start_button.setEnabled(not self.running and self.active is None and any(j.status == "Queued" for j in self.jobs))
        selected = self.selected_worker()
        self.cancel_button.setEnabled(selected is not None and not selected.finalizing)
        self.remove_button.setEnabled(self.active is None and bool(self.jobs) and self.table.currentRow() >= 0)
        self.clear_button.setEnabled(self.active is None and any(j.status not in {"Queued", "Running"} for j in self.jobs))
        self.retry_button.setEnabled(self.active is None and 0 <= self.table.currentRow() < len(self.jobs) and self.jobs[self.table.currentRow()].status in {"Failed", "Cancelled"})
        if row is None or row == self.table.currentRow():
            self.show_details()

    def selection_changed(self):
        worker = self.selected_worker()
        self.cancel_button.setEnabled(worker is not None and not worker.finalizing)
        row = self.table.currentRow()
        self.refresh(row if row >= 0 else None)
        self.tick_activity()

    def show_details(self):
        row = self.table.currentRow()
        self.open_book.setEnabled(False)
        if not 0 <= row < len(self.jobs):
            self.details.clear()
            return
        job = self.jobs[row]
        lines = [job.metadata.get("title", "Story information"), ""]
        if job.metadata:
            wording = "calculated from downloaded text" if job.metadata.get("wordCountSource") == "calculated" else "reported by the site"
            lines.append(f"Words: {display_words(job.metadata)} ({wording})" if job.metadata.get("numWords") else "Words: not reported by the site; available after download")
        lines.extend([f"Status: {job.status}", f"Source: {job.request['source']}"])
        for key, name in (("author", "Author"), ("numChapters", "Chapters"), ("status", "Story status"), ("dateUpdated", "Updated")):
            if job.metadata.get(key):
                lines.append(f"{name}: {job.metadata[key]}")
        worker = self.selected_worker()
        if worker:
            lines.extend(["", worker.message, f"Elapsed: {worker.elapsed.elapsed() // 1000}s"])
        if job.result.get("cached"):
            lines.append("Reused recent preview metadata.")
        if job.result.get("path"):
            lines.extend(["", "Saved file:", job.result["path"]])
            self.open_book.setEnabled(Path(job.result["path"]).is_file())
        if job.result.get("backup"):
            lines.extend(["", "Original backup:", job.result["backup"]])
        if job.result.get("urls"):
            lines.extend(["", "Extracted links:", *job.result["urls"]])
        if job.error:
            lines.extend(["", job.error, "", "For login, cookies, or site-specific options, select a personal.ini file and retry."])
        self.details.setPlainText("\n".join(lines))

    def open_selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.jobs):
            path = self.jobs[row].result.get("path")
            if path:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def remove_selected(self):
        row = self.table.currentRow()
        if self.active is None and 0 <= row < len(self.jobs):
            self.jobs.pop(row)
            self.rendered_rows.clear()
            self.refresh()

    def clear_finished(self):
        if self.active is None:
            self.jobs = [job for job in self.jobs if job.status == "Queued"]
            self.rendered_rows.clear()
            self.refresh()

    def retry_selected(self):
        row = self.table.currentRow()
        if self.active is None and 0 <= row < len(self.jobs) and self.jobs[row].status in {"Failed", "Cancelled"}:
            old = self.jobs[row]
            request = dict(old.request, ini=self.ini.text() or None, adult=self.adult.isChecked())
            self.jobs[row] = Job(request)
            self.refresh()

    def start_queue(self):
        self.running = True
        self.next_job()

    def source_key(self, request):
        if request["operation"] == "update":
            return str(Path(request["source"]).expanduser().resolve())
        return request["source"]

    def remember_affinity(self, source, worker):
        self.affinity.pop(source, None)
        self.affinity[source] = worker
        while len(self.affinity) > 256:
            self.affinity.pop(next(iter(self.affinity)))

    def next_job(self):
        if not self.running or self.closing:
            return
        busy_sources = {self.source_key(self.jobs[w.active].request) for w in self.workers if w.active is not None}
        for row, job in enumerate(self.jobs):
            if job.status != "Queued":
                continue
            source = self.source_key(job.request)
            if source in busy_sources:
                continue
            idle = [worker for worker in self.workers if worker.active is None]
            if not idle:
                break
            owner = self.affinity.get(source)
            worker = owner if owner in idle else idle[0]
            self.remember_affinity(source, worker)
            busy_sources.add(source)
            worker.start(row)
            if self.table.currentRow() < 0:
                self.table.selectRow(row)
        if self.active is None:
            self.running = False
            self.activity_timer.stop()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            failed = sum(job.status == "Failed" for job in self.jobs)
            self.message.setText(f"Queue finished. {failed} failed job(s)." if failed else "Queue finished. Your stories are ready.")
            self.refresh()
        else:
            self.activity_timer.start()
            self.tick_activity()

    def tick_activity(self):
        active = [worker for worker in self.workers if worker.active is not None]
        if not active:
            self.activity_timer.stop()
            if not self.running:
                self.progress.setRange(0, 100)
                self.progress.setValue(0)
                if any(job.status == "Queued" for job in self.jobs):
                    self.message.setText("Queue ready. Start queue to continue.")
            return
        worker = self.selected_worker() or active[0]
        self.progress.setRange(0, 0 if worker.percent is None else 100)
        if worker.percent is not None:
            self.progress.setValue(worker.percent)
        self.message.setText(f"{len(active)} active · {worker.message}  ({worker.elapsed.elapsed() // 1000}s elapsed)")

    def handle_event(self, worker, event):
        if worker.active is None:
            return
        row = worker.active
        job = self.jobs[row]
        kind = event.get("type")
        if kind in {"activity", "progress"}:
            worker.percent = event.get("percent")
            worker.message = event["message"]
            if event.get("finalizing"):
                worker.finalizing = True
            self.tick_activity()
        elif kind == "metadata":
            job.metadata = event["metadata"]
        elif kind == "result":
            worker.result_received = True
            job.result = event
            job.metadata = event.get("metadata", job.metadata)
            job.status = "Up to date" if event.get("status") == "unchanged" else "Done"
            if event.get("path"):
                self.remember_affinity(str(Path(event["path"]).resolve()), worker)
            if job.request["operation"] == "extract":
                extracted = "\n".join(event.get("urls", []))
                current = self.urls.toPlainText().strip()
                self.urls.setPlainText("\n".join(filter(None, [current, extracted])))
            QTimer.singleShot(0, worker.complete)
        elif kind == "error":
            job.error = event["message"]
            job.status = "Failed"
            QTimer.singleShot(0, lambda: worker.complete(1))
        self.refresh(row)

    def cancel_current(self):
        worker = self.selected_worker()
        if worker and not worker.finalizing:
            self.running = False
            self.message.setText("Cancelling selected job. Other active jobs finish; remaining jobs stay queued.")
            worker.cancel()
            self.refresh()

    def closeEvent(self, event):
        if self.active is not None:
            if any(worker.finalizing for worker in self.workers if worker.active is not None):
                self.message.setText("Finishing the save. Close the window when it completes.")
                event.ignore()
                return
            reply = QMessageBox.question(self, "Downloads in progress", "Cancel active downloads and close?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.closing = True
        self.running = False
        for worker in self.workers:
            worker.shutdown()
        self.network_work.cleanup()
        self.save_settings()
        event.accept()


def run():
    app = QApplication(sys.argv)
    app.setApplicationName("FanFicFare Desktop")
    app.setOrganizationName("FanFicFare Desktop")
    app.setStyle("Fusion")
    apply_theme(app)
    window = Window()
    window.show()
    return app.exec()
