"""PyInstaller entry point (absolute imports work outside a package)."""
from fanficfare_gui.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
