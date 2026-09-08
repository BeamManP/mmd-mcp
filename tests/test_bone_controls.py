import copy
import ctypes
import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from mmd_mcp import bone_controls as bones
from mmd_mcp.windows import MMDWindow

ANCHOR = ("0", 1, "初音ミク")
VALUES = {"position": {"x": 0.0, "y": 0.0, "z": 0.0},
          "rotation_degrees": {"x": 0.0, "y": 0.0, "z": 0.0}}


def reader_fixture():
    reader = MagicMock()
    reader.target = MMDWindow(123, 456, "MikuMikuDance", False, 1.0)
    reader.anchor.return_value = ANCHOR
    reader.control.side_effect = lambda control_id, _: control_id
    reader.text.side_effect = lambda hwnd: "カメラ編" if hwnd == 536 else "0.0"
    return reader


class InputTests(unittest.TestCase):
    def test_omitted_axes_are_not_written(self):
        updates = bones.build_updates(None, bones.AxisValues(x=10))
        self.assertEqual(updates, [("rotation_degrees", "x", 547, 10.0)])

    def test_no_values_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            bones.build_updates(bones.AxisValues(), None)

    def test_nonfinite_boolean_and_unknown_axis_are_rejected(self):
        for kwargs in ({"x": float("nan")}, {"x": float("inf")}, {"x": True},
                       {"x": "10"}, {"x": 100001}, {"w": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                bones.AxisValues(**kwargs)


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.reader = reader_fixture()

    def test_camera_selector_is_refused(self):
        self.reader.anchor.return_value = ("0", 0, "camera")
        with self.assertRaisesRegex(ValueError, "Select a model"):
            bones._active_panel(self.reader)

    def test_camera_edit_mode_is_refused(self):
        self.reader.text.return_value = "ボーン編"
        self.reader.text.side_effect = None
        with self.assertRaisesRegex(ValueError, "bone editing mode"):
            bones._active_panel(self.reader)

    @patch("mmd_mcp.bone_controls.win32gui.IsWindowVisible", return_value=False)
    @patch("mmd_mcp.bone_controls._message", return_value=1)
    def test_playback_is_refused(self, *_):
        with self.assertRaisesRegex(ValueError, "Stop MMD playback"):
            bones._active_panel(self.reader)


class NativeCommitTests(unittest.TestCase):
    def test_commit_targets_only_the_chosen_edit_not_the_main_window(self):
        reader = reader_fixture()
        calls = []

        def native(hwnd, message, wparam=0, lparam=0):
            calls.append((hwnd, message, wparam,
                          ctypes.wstring_at(lparam) if message == bones.WM_SETTEXT else lparam))
            return 1 if message == bones.WM_SETTEXT else 0

        with patch("mmd_mcp.bone_controls._message", side_effect=native):
            bones._commit_edit(reader, 547, 10)
        self.assertEqual(calls, [(547, bones.WM_SETTEXT, 0, "10"),
                                 (547, bones.WM_KEYDOWN, 13, 1)])

    def test_registration_control_cannot_be_used_as_a_transform_field(self):
        with patch("mmd_mcp.bone_controls._message") as native:
            with self.assertRaisesRegex(ValueError, "six bone"):
                bones._commit_edit(reader_fixture(), 500, 1)
            native.assert_not_called()


class OperationTests(unittest.TestCase):
    def setUp(self):
        identity = {"model_name": "初音ミク", "selected_bone_name": "センター",
                    "selected_bone_index": 0, "selection_count": 1, "_guard": (0,)}
        patcher = patch("mmd_mcp.bone_controls.selected_identity", return_value=identity)
        self.identity = patcher.start()
        self.addCleanup(patcher.stop)

    def test_wrong_expected_bone_fails_before_writing(self):
        with patch("mmd_mcp.bone_controls.UIReader", return_value=reader_fixture()), \
             patch("mmd_mcp.bone_controls._active_panel", return_value=(ANCHOR, VALUES)), \
             patch("mmd_mcp.bone_controls._commit_edit") as commit:
            with self.assertRaisesRegex(ValueError, "expected bone"):
                bones.set_selected_bone_transform(rotation_degrees=bones.AxisValues(z=5), expected_bone_name="左腕")
            commit.assert_not_called()

    def test_selection_change_stops_before_writing(self):
        identity = self.identity.return_value
        self.identity.side_effect = [identity, {**identity, "selected_bone_name": "左腕"}]
        with patch("mmd_mcp.bone_controls.UIReader", return_value=reader_fixture()), \
             patch("mmd_mcp.bone_controls._active_panel", return_value=(ANCHOR, VALUES)), \
             patch("mmd_mcp.bone_controls._commit_edit") as commit:
            with self.assertRaisesRegex(RuntimeError, "context"):
                bones.set_selected_bone_transform(rotation_degrees=bones.AxisValues(z=5))
            commit.assert_not_called()

    def test_context_change_stops_before_first_write(self):
        reader = reader_fixture()
        with patch("mmd_mcp.bone_controls.UIReader", return_value=reader), \
             patch("mmd_mcp.bone_controls._active_panel", side_effect=[(ANCHOR, VALUES), (("1", 1, "初音ミク"), VALUES)]), \
             patch("mmd_mcp.bone_controls._commit_edit") as commit:
            with self.assertRaisesRegex(RuntimeError, "context"):
                bones.set_selected_bone_transform(rotation_degrees=bones.AxisValues(x=10))
            commit.assert_not_called()

    def test_partial_failure_is_explicit_and_lock_is_released(self):
        reader = reader_fixture()
        changed = copy.deepcopy(VALUES)
        changed["position"]["x"] = 1
        for _ in range(2):
            with patch("mmd_mcp.bone_controls.UIReader", return_value=reader), \
                 patch("mmd_mcp.bone_controls._active_panel", side_effect=[(ANCHOR, VALUES), (ANCHOR, VALUES), (ANCHOR, changed), (ANCHOR, changed)]), \
                 patch("mmd_mcp.bone_controls._commit_edit", side_effect=[None, RuntimeError("timeout")]):
                with self.assertRaisesRegex(RuntimeError, "Partial changes remain"):
                    bones.set_selected_bone_transform(position=bones.AxisValues(x=1, y=2))


if __name__ == "__main__":
    unittest.main()
