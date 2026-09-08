"""Read-only discovery and validation of MMD top-level windows."""

from dataclasses import asdict, dataclass

import psutil
import pywintypes
import win32con
import win32gui
import win32process


@dataclass(frozen=True)
class MMDWindow:
    hwnd: int
    pid: int
    title: str
    minimized: bool
    process_started: float

    def public_info(self) -> dict:
        return {key: value for key, value in asdict(self).items()
                if key != "process_started"}


def list_windows() -> list[MMDWindow]:
    """Only expose visible, unowned windows owned by MikuMikuDance.exe."""
    result = []

    def visit(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process = psutil.Process(pid)
            if process.name().casefold() != "mikumikudance.exe":
                return
            result.append(MMDWindow(
                hwnd, pid, win32gui.GetWindowText(hwnd),
                bool(win32gui.IsIconic(hwnd)), process.create_time(),
            ))
        except (psutil.Error, pywintypes.error):
            # A process/window can disappear while EnumWindows is running.
            return

    win32gui.EnumWindows(visit, None)
    return sorted(result, key=lambda window: (window.pid, window.hwnd))


def select_window(hwnd: int | None = None) -> MMDWindow:
    windows = list_windows()
    candidates = windows if hwnd is None else [w for w in windows if w.hwnd == hwnd]
    if not candidates:
        raise ValueError("MMD window not found. Open MikuMikuDance and list windows again.")
    if len(candidates) != 1:
        raise ValueError("Multiple MMD windows found. Specify hwnd from mmd_list_windows.")
    window = candidates[0]
    if window.minimized:
        raise ValueError("MMD is minimized. Restore its window before capturing.")
    if not win32gui.IsWindowEnabled(window.hwnd):
        raise ValueError("MMD has a modal dialog open. Close it before capturing.")
    return window
