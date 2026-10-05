import sys


def main():
    if "--worker" in sys.argv:
        # Windows windowed bundles set Python's stdio to None even when
        # QProcess supplies pipes. Recover the inherited Win32 handles.
        if sys.platform == "win32" and sys.stdout is None:
            import ctypes
            from ctypes import wintypes
            import msvcrt
            import os
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetStdHandle.argtypes = [wintypes.DWORD]
            kernel.GetStdHandle.restype = wintypes.HANDLE
            for name, number, mode, flag in (("stdin", -10, "r", os.O_RDONLY), ("stdout", -11, "w", os.O_WRONLY), ("stderr", -12, "w", os.O_WRONLY)):
                handle = kernel.GetStdHandle(wintypes.DWORD(number))
                fd = msvcrt.open_osfhandle(handle, flag)
                setattr(sys, name, os.fdopen(fd, mode, encoding="utf-8", buffering=1))
        from .worker import main as worker_main
        return worker_main()
    from .app import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
