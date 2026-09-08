"""One-shot WGC worker. Isolated so native hangs cannot block the MCP server."""

import argparse
from pathlib import Path

import cv2
from windows_capture import Frame, InternalCaptureControl, WindowsCapture

from .windows import select_window


def capture(hwnd: int, pid: int, started: float, destination: Path) -> None:
    target = select_window(hwnd)
    if (target.pid, target.process_started) != (pid, started):
        raise ValueError("MMD process changed. List windows again.")
    session = WindowsCapture(
        window_hwnd=target.hwnd, cursor_capture=False,
        # Keep the OS default border; no permission/config changes needed.
        draw_border=None,
    )
    written = False

    @session.event
    def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
        nonlocal written
        if written:
            control.stop()
            return
        # Encode in the callback while the native pixel buffer is valid.
        ok, encoded = cv2.imencode(".png", frame.frame_buffer[:, :, :3])
        if not ok:
            raise RuntimeError("PNG encoding failed.")
        destination.write_bytes(encoded.tobytes())
        written = True
        control.stop()

    @session.event
    def on_closed():
        pass

    session.start()
    if not written:
        raise RuntimeError("MMD closed before a frame was received.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("hwnd", type=int)
    parser.add_argument("pid", type=int)
    parser.add_argument("started", type=float)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    capture(args.hwnd, args.pid, args.started, args.destination)


if __name__ == "__main__":
    main()
