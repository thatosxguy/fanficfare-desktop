"""Build on each target OS; PyInstaller does not cross-compile."""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
environment = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(root / "build" / "pyinstaller-cache"))
subprocess.run([
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
    "--windowed", "--onedir", "--name", "FanFicFare Desktop",
    "--paths", str(root / "src"),
    "--collect-data", "fanficfare_gui",
    "--icon", str(root / "src" / "fanficfare_gui" / "assets" / "app-icon.png"),
    "--collect-all", "fanficfare", "--collect-all", "cloudscraper",
    "--copy-metadata", "FanFicFare", "--copy-metadata", "fanficfare-desktop",
    "--osx-bundle-identifier", "org.fanficfare.desktop",
    str(root / "scripts" / "desktop_entry.py"),
], cwd=root, env=environment, check=True)
