"""Verify the packaged worker protocol and GUI startup on the build host."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import zipfile

from fanficfare_gui.network import initialize_pacing

root = Path(__file__).resolve().parents[1]
if sys.platform == "darwin":
    executable = root / "dist" / "FanFicFare Desktop.app" / "Contents" / "MacOS" / "FanFicFare Desktop"
else:
    executable = root / "dist" / "FanFicFare Desktop" / ("FanFicFare Desktop.exe" if sys.platform == "win32" else "FanFicFare Desktop")

with tempfile.TemporaryDirectory() as directory:
    for source, expected in (("http://test1.com?sid=1[1-2]", "result"), ("http://test1.com?sid=666", "error")):
        request = {"operation": "download", "source": source, "format": "epub", "output": directory}
        process = subprocess.run([str(executable), "--worker"], input=json.dumps(request) + "\n", text=True, encoding="utf-8", capture_output=True, timeout=45)
        events = [json.loads(line) for line in process.stdout.splitlines()]
        assert events and events[-1]["type"] == expected, (process.returncode, process.stdout, process.stderr)
        assert process.returncode == (0 if expected == "result" else 1)
        if expected == "result":
            with zipfile.ZipFile(events[-1]["path"]) as book:
                assert book.testzip() is None
        print(f"Packaged worker: {expected} verified")

    preview = {"operation": "preview", "source": "http://test1.com?sid=674[1-2]", "format": "epub", "output": directory}
    requests = [preview, preview, dict(preview, operation="download")]
    process = subprocess.run([str(executable), "--worker"], input="".join(json.dumps(request) + "\n" for request in requests), text=True, encoding="utf-8", capture_output=True, timeout=45)
    events = [json.loads(line) for line in process.stdout.splitlines()]
    results = [event for event in events if event["type"] == "result"]
    assert process.returncode == 0 and len(results) == 3, (process.stdout, process.stderr)
    assert results[1]["cached"] is True
    assert results[2]["metadata"]["wordCountSource"] == "calculated"
    assert int(results[2]["metadata"]["numWords"].replace(",", "")) > 100
    print("Packaged worker: session reuse and calculated word counts verified")

    pacing = str(Path(directory) / "pacing.sqlite")
    initialize_pacing(pacing)
    children = []
    for source in ("http://test1.com?sid=1[1-2]", "http://test1.com?sid=674[1-2]"):
        child = subprocess.Popen([str(executable), "--worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        request = {"operation": "download", "source": source, "format": "epub", "output": directory, "pacing_db": pacing}
        child.stdin.write(json.dumps(request) + "\n")
        child.stdin.close()
        child.stdin = None
        children.append(child)
    try:
        paths = []
        for child in children:
            stdout, stderr = child.communicate(timeout=45)
            events = [json.loads(line) for line in stdout.splitlines()]
            assert child.returncode == 0 and events[-1]["type"] == "result", (stdout, stderr)
            paths.append(events[-1]["path"])
            with zipfile.ZipFile(paths[-1]) as book:
                assert book.testzip() is None
        assert len(set(paths)) == 2
        print("Packaged workers: two simultaneous downloads with shared pacing database verified")
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)

environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
process = subprocess.Popen([str(executable)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    stdout, stderr = process.communicate(timeout=4)
    raise AssertionError(f"GUI exited early: {process.returncode}, {stdout!r}, {stderr!r}")
except subprocess.TimeoutExpired:
    process.terminate()
    process.communicate(timeout=10)
    print("Packaged GUI: startup verified")
