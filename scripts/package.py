"""Archive native apps while preserving executable permissions and symlinks."""

from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile


root = Path(__file__).resolve().parents[1]
destination = root / "dist" / "artifacts"
destination.mkdir(parents=True, exist_ok=True)
architecture = platform.machine().lower()
architecture = {"aarch64": "arm64", "amd64": "x86_64"}.get(architecture, architecture)

if sys.platform == "darwin":
    bundle = root / "dist" / "FanFicFare Desktop.app"
    output = destination / f"FanFicFare-Desktop-macOS-{architecture}.zip"
    if not bundle.is_dir():
        raise SystemExit("Build the native app before packaging it.")
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(output)], check=True)
elif sys.platform == "win32":
    bundle = root / "dist" / "FanFicFare Desktop"
    if not bundle.is_dir():
        raise SystemExit("Build the native app before packaging it.")
    output = Path(shutil.make_archive(str(destination / f"FanFicFare-Desktop-Windows-{architecture}"), "zip", root_dir=bundle.parent, base_dir=bundle.name))
else:
    bundle = root / "dist" / "FanFicFare Desktop"
    if not bundle.is_dir():
        raise SystemExit("Build the native app before packaging it.")
    output = destination / f"FanFicFare-Desktop-Linux-{architecture}.tar.gz"
    with tarfile.open(output, "w:gz") as archive:
        archive.add(bundle, arcname=bundle.name)

print(output)
