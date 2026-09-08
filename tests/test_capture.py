"""Guardrails for capture failures; no live MMD required."""

import subprocess
import unittest
from unittest.mock import patch

from mmd_mcp.capture import capture_png
from mmd_mcp.windows import MMDWindow, select_window

WINDOW = MMDWindow(123, 456, "MikuMikuDance", False, 1.0)


class SelectionTests(unittest.TestCase):
    @patch("mmd_mcp.windows.list_windows", return_value=[])
    def test_missing_mmd(self, _):
        with self.assertRaisesRegex(ValueError, "not found"):
            select_window()

    @patch("mmd_mcp.windows.list_windows", return_value=[WINDOW, MMDWindow(124, 457, "MikuMikuDance", False, 2.0)])
    def test_multiple_instances_require_explicit_target(self, _):
        with self.assertRaisesRegex(ValueError, "Multiple"):
            select_window()
        with patch("mmd_mcp.windows.win32gui.IsWindowEnabled", return_value=True):
            self.assertEqual(select_window(124).pid, 457)

    @patch("mmd_mcp.windows.list_windows", return_value=[WINDOW])
    def test_unknown_handle_is_not_replaced_with_another_window(self, _):
        with self.assertRaisesRegex(ValueError, "not found"):
            select_window(999)

    @patch("mmd_mcp.windows.list_windows", return_value=[MMDWindow(123, 456, "MikuMikuDance", True, 1.0)])
    def test_minimized_window_is_not_captured(self, _):
        with self.assertRaisesRegex(ValueError, "minimized"):
            select_window()

    @patch("mmd_mcp.windows.list_windows", return_value=[WINDOW])
    @patch("mmd_mcp.windows.win32gui.IsWindowEnabled", return_value=False)
    def test_modal_dialog_is_reported(self, *_):
        with self.assertRaisesRegex(ValueError, "modal"):
            select_window()


class WorkerFailureTests(unittest.TestCase):
    @patch("mmd_mcp.capture.select_window", return_value=WINDOW)
    @patch("mmd_mcp.capture.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 1))
    def test_timeout_releases_capture_lock_for_retry(self, *_):
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                capture_png(timeout_seconds=1)

    @patch("mmd_mcp.capture.select_window", return_value=WINDOW)
    @patch("mmd_mcp.capture.subprocess.run", return_value=subprocess.CompletedProcess([], 1, b"", b"device failure"))
    def test_native_failure_is_reported(self, *_):
        with self.assertRaisesRegex(RuntimeError, "device failure"):
            capture_png()


if __name__ == "__main__":
    unittest.main()
