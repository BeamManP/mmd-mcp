"""Bounded, serialized screenshot requests."""

import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .windows import select_window

_capture_lock = threading.Lock()


def capture_png(hwnd: int | None = None, timeout_seconds: float = 15) -> bytes:
    if not 1 <= timeout_seconds <= 30:
        raise ValueError("timeout_seconds must be between 1 and 30.")
    if not _capture_lock.acquire(blocking=False):
        raise RuntimeError("A capture is already in progress. Retry after it finishes.")
    try:
        target = select_window(hwnd)
        with tempfile.TemporaryDirectory(prefix="mmd-mcp-") as directory:
            output = Path(directory) / "frame.png"
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "mmd_mcp.capture_worker",
                     str(target.hwnd), str(target.pid), str(target.process_started), str(output)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=timeout_seconds, creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    "MMD capture timed out. Ensure the desktop is unlocked and MMD is restored."
                ) from exc
            if result.returncode:
                detail = result.stderr.decode("utf-8", errors="replace")[-2000:]
                raise RuntimeError(f"Capture worker failed ({result.returncode}): {detail}")
            data = output.read_bytes()
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError("Capture worker did not return a PNG.")
            return data
    finally:
        _capture_lock.release()
