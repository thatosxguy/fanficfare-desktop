"""Session worker. stdout carries newline-delimited JSON only."""

from contextlib import redirect_stdout
import json
import sys


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    channel = sys.stdout

    def emit(event):
        channel.write(json.dumps(event, ensure_ascii=False) + "\n")
        channel.flush()

    with redirect_stdout(sys.stderr):
        from .engine import execute
        from .session import Session
        session = Session()
    status = 0
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                with redirect_stdout(sys.stderr):
                    result = execute(request, emit, session)
                emit({"type": "result", **result})
                status = 0
            except Exception as error:
                emit({"type": "error", "message": f"{type(error).__name__}: {error}"})
                status = 1
    finally:
        session.close()
    return status
