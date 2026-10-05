"""FanFicFare integration, isolated from the GUI and its event loop."""

from datetime import datetime
from importlib.resources import files
from html.parser import HTMLParser
from pathlib import Path
import os
import re
import shutil
import hashlib
import tempfile
import uuid
import zipfile
from urllib.parse import urlparse

from fanficfare import adapters, writers
from fanficfare.configurable import Configuration
from fanficfare.epubutils import get_dcsource_chaptercount, get_update_data
from fanficfare.geturls import get_urls_from_page

from .session import Session
from .network import attach_pacing


FORMATS = {"epub": ".epub", "html": ".html.zip", "txt": ".txt", "mobi": ".mobi"}
DEFAULTS = files("fanficfare").joinpath("defaults.ini").read_text(encoding="utf-8")
WORDS = re.compile(r"\b\w+(?:['’\-]\w+)*\b", re.UNICODE)


def parse_urls(text):
    """Validate one URL per line while preserving order and chapter ranges."""
    result = []
    for line in text.splitlines():
        url = line.strip()
        if not url or url.startswith("#"):
            continue
        if not re.match(r"^https?://[^\s]+$", url, re.I):
            raise ValueError(f"Enter one complete http or https URL per line: {url}")
        if url not in result:
            result.append(url)
    if not result:
        raise ValueError("Paste at least one story URL first.")
    return result


def safe_name(text):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(text)).strip(" .")[:160]
    if not value:
        value = "Untitled"
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "_" + value
    return value


def configuration(url, fmt, ini=None, adult=False, unknown=False):
    sections = ["unknown"] if unknown else adapters.getConfigSectionsFor(url)
    config = Configuration(sections, fmt)
    config.read_string(DEFAULTS)
    # Use only the selected file; do not silently inherit another app's INI.
    if ini:
        with Path(ini).expanduser().open(encoding="utf-8-sig") as stream:
            config.read_file(stream)
    if not config.has_section("overrides"):
        config.add_section("overrides")
    overrides = {
        "always_overwrite": "true", "continue_on_chapter_error": "false",
        "make_directories": "false", "zip_output": "true" if fmt == "html" else "false",
    }
    if fmt not in ("epub", "html"):
        overrides["include_images"] = "false"
    if adult:
        overrides["is_adult"] = "true"
    for key, value in overrides.items():
        config.set("overrides", key, value)
    return config


def metadata_summary(story):
    keys = ("title", "author", "storyUrl", "site", "numChapters", "numWords", "status", "dateUpdated", "description")
    result = {key: str(story.getMetadata(key) or "") for key in keys}
    result["wordCountSource"] = "site" if result["numWords"] else "unavailable"
    return result


class ChapterText(HTMLParser):
    """Extract countable text without constructing a second HTML tree."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"} and self.hidden is None:
            self.hidden = tag

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag == self.hidden:
            self.hidden = None

    def handle_data(self, data):
        if self.hidden is None and data.strip():
            self.parts.append(data.strip())


def html_word_count(chapters):
    """Count chapter text while leaving the original markup untouched."""
    count = 0
    for html in chapters:
        parser = ChapterText()
        parser.feed(str(html or ""))
        parser.close()
        count += sum(1 for _ in WORDS.finditer(" ".join(parser.parts)))
    return count


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def text_word_count(story):
    return html_word_count(chapter.get("html") for chapter in story.getChapters())


def attach_page_progress(config, cache, emit):
    fetcher = config.get_fetcher()
    original = fetcher.do_request
    phase = {"percent": None, "count": 0}

    def request(*args, **kwargs):
        url = args[1] if len(args) > 1 else kwargs.get("url", "")
        image = kwargs.get("image", False)
        phase["count"] += 1
        host = urlparse(url).hostname or "local source"
        noun = "image" if image else "page"
        emit({"type": "activity", "message": f"Loading {noun} {phase['count']} from {host}…", "percent": phase["percent"]})
        response = original(*args, **kwargs)
        action = "Reused cached" if response.fromcache else "Loaded"
        emit({"type": "activity", "message": f"{action} {noun} {phase['count']} from {host}.", "percent": phase["percent"]})
        return response

    fetcher.do_request = request
    return phase


def validate_output(path, fmt):
    if not path.is_file() or not path.stat().st_size:
        raise ValueError("FanFicFare did not produce a complete output file.")
    if fmt in ("epub", "html"):
        with zipfile.ZipFile(path) as archive:
            if archive.testzip():
                raise ValueError("The downloaded archive failed its integrity check.")
            if fmt == "epub" and archive.read("mimetype") != b"application/epub+zip":
                raise ValueError("The downloaded file is not an EPUB.")


def publish_new(staged, directory, name, extension):
    """Reserve a unique destination without overwriting existing books."""
    for number in range(1, 10001):
        suffix = "" if number == 1 else f" ({number})"
        target = directory / f"{safe_name(name)}{suffix}{extension}"
        try:
            # Work is staged on the destination filesystem. Linking publishes
            # the complete book atomically and fails if the name already exists.
            os.link(staged, target)
        except FileExistsError:
            continue
        return target
    raise ValueError("Too many files have the same name. Choose another destination.")


def execute(request, emit=lambda event: None, session=None):
    session = session or Session()
    operation = request["operation"]
    fmt = request.get("format", "epub").lower()
    if fmt not in FORMATS:
        raise ValueError("Unsupported output format.")
    url = request["source"]
    original = None
    previous_count = None
    original_hash = None
    if operation == "update":
        fmt = "epub"
        original = Path(url).expanduser().resolve(strict=True)
        original_hash = file_digest(original)
        url, previous_count = get_dcsource_chaptercount(str(original))
        if not url or not previous_count:
            raise ValueError("This EPUB has no recognizable FanFicFare source or chapters.")
    if operation not in {"download", "update", "preview", "extract"}:
        raise ValueError("Unknown job operation.")
    config = configuration(url, fmt, request.get("ini"), request.get("adult", False), operation == "extract")
    if operation != "extract":
        url, begin, end = adapters.get_url_chapter_range(url)
        adapter = adapters.getAdapter(config, url)
        adapter.setChaptersRange(begin, end)
    scope = session.scope(request, config)
    if operation == "preview":
        cached = session.preview(scope, request["source"])
        if cached:
            emit({"type": "metadata", "metadata": cached, "cached": True})
            return {"status": "done", "metadata": cached, "cached": True}
        # get_cover=False alone does not stop Literotica's adapter from calling
        # setCoverImage. Explicit image/cover overrides cover both code paths.
        config.set("overrides", "include_images", "false")
        config.set("overrides", "never_make_cover", "true")
    cache, cookies = session.pages(scope)
    config.set_basic_cache(cache)
    if cookies is not None:
        config.set_cookiejar(cookies)
    session.connect(scope, config)
    attach_pacing(config, request.get("pacing_db"), emit)
    phase = attach_page_progress(config, cache, emit)
    if operation == "extract":
        urls = get_urls_from_page(url, config, normalize=True).get("urllist", [])
        session.remember_cookies(scope, config.get_cookiejar())
        return {"status": "done", "urls": list(dict.fromkeys(urls))}
    emit({"type": "activity", "percent": None, "message": "Reading story information…"})
    story = adapter.getStoryMetadataOnly(get_cover=operation != "preview")
    cache.capture_metadata = False
    session.remember_cookies(scope, config.get_cookiejar())
    summary = metadata_summary(story)
    emit({"type": "metadata", "metadata": summary})
    if operation == "preview":
        session.remember_preview(scope, request["source"], summary)
        return {"status": "done", "metadata": summary}
    if original:
        count = story.getChapterCount()
        if count == previous_count:
            if not summary["numWords"]:
                words = session.word_count(original_hash)
                if words is None:
                    words = html_word_count(get_update_data(str(original))[2])
                    session.remember_word_count(original_hash, words)
                summary["numWords"] = str(words)
                summary["wordCountSource"] = "calculated"
                emit({"type": "metadata", "metadata": summary})
            return {"status": "unchanged", "metadata": summary, "path": str(original)}
        if count < previous_count:
            raise ValueError(f"The source has {count} chapters but your EPUB has {previous_count}. Update stopped to preserve your chapters.")
        (_, _, adapter.oldchapters, adapter.oldimgs, adapter.oldcover,
         adapter.calibrebookmark, adapter.logfile, adapter.oldchaptersmap,
         adapter.oldchaptersdata) = get_update_data(str(original))[:9]
        config.set("overrides", "never_make_cover", "true")
    directory = original.parent if original else Path(request["output"]).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # The parent GUI owns this folder so it can also remove partial work on cancellation.
    parent_work = request.get("work_dir")
    with tempfile.TemporaryDirectory(prefix=".fff-", dir=parent_work or directory) as temporary:
        staged = Path(temporary) / ("story" + FORMATS[fmt])
        config.set("overrides", "output_filename", str(staged))
        phase["percent"] = 0
        def chapter_progress(fraction, _):
            percent = min(99, int(fraction * 100))
            phase["percent"] = percent
            emit({"type": "progress", "percent": percent, "message": "Downloading chapters…"})
        full_story = adapter.getStory(notification=chapter_progress)
        if adapter.story.chapter_error_count:
            raise ValueError("Some chapters failed to download. The incomplete file was discarded.")
        if not summary["numWords"]:
            full_story.setMetadata("numWords", text_word_count(full_story))
            summary["numWords"] = str(full_story.getMetadata("numWords"))
            summary["wordCountSource"] = "calculated"
            emit({"type": "metadata", "metadata": summary})
        writers.getWriter(fmt, config, adapter).writeStory(
            outfilename=str(staged), forceOverwrite=True,
            notification=chapter_progress,
        )
        session.remember_preview(scope, request["source"], summary)
        validate_output(staged, fmt)
        if fmt == "epub" and summary["wordCountSource"] == "calculated":
            session.remember_word_count(file_digest(staged), summary["numWords"])
        emit({"type": "progress", "percent": 99, "message": "Saving validated book…", "finalizing": True})
        if original:
            if file_digest(original) != original_hash:
                raise ValueError("The original EPUB changed during the download. Update stopped; retry when other editors are closed.")
            backup_dir = directory / "FanFicFare Backups"
            backup_dir.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = backup_dir / f"{safe_name(original.stem)}-{stamp}-{uuid.uuid4().hex[:8]}.epub"
            shutil.copy2(original, backup)
            os.replace(staged, original)
            target = original
        else:
            backup = None
            target = publish_new(staged, directory, f"{summary['title']} - {summary['author']}", FORMATS[fmt])
        return {"status": "done", "metadata": summary, "path": str(target), "backup": str(backup) if backup else None}
