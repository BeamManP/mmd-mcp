"""Build the native bridge and a Windows x64 wheel containing it."""

import os
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

def main():
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise RuntimeError("Build with 64-bit Python on Windows.")
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    subprocess.run(["cmd", "/c", str(root / "scripts" / "build_native.cmd")], check=True)
    native = root / "src" / "mmd_mcp" / "_native" / "mmd_selection.dll"
    if not native.is_file():
        raise RuntimeError("Native bridge build produced no DLL.")
    # pip provides the isolated build requirements from pyproject.toml, so the
    # user's runtime environment need not contain wheel/setuptools build tools.
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(root / "dist"),
                    "--config-settings", "--build-option=--plat-name=win_amd64", str(root)], check=True)
    packages = list((root / "dist").glob("mmd_mcp-*-py3-none-win_amd64.whl"))
    if not packages:
        raise RuntimeError("No Windows x64 wheel was produced.")
    package = max(packages, key=lambda path: path.stat().st_mtime_ns)
    with zipfile.ZipFile(package) as wheel:
        if wheel.read("mmd_mcp/_native/mmd_selection.dll") != native.read_bytes():
            raise RuntimeError("Wheel contains a missing or outdated native bridge.")
        if any(name.startswith(("local/", "captures/")) or name.lower().endswith((".pmd", ".pmx", ".pmm", ".vmd", ".vpd")) for name in wheel.namelist()):
            raise RuntimeError("Unexpected user/test asset in the wheel.")
    print(f"Verified wheel: {package}")


if __name__ == "__main__":
    main()
