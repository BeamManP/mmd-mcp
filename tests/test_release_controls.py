import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from mmd_mcp import scene_settings as settings, scene_lifecycle as lifecycle
from mmd_mcp import file_operations as files
from mmd_mcp.playback import PlaybackOptions
from mmd_mcp.render_controls import GravityValues, OutputSize
from mmd_mcp.timeline_transforms import TransformSpec
from mmd_mcp.video_export import VideoOptions


class SettingsTests(unittest.TestCase):
    def test_strict_flags_and_unknown_settings_rejected(self):
        for data in ({"axis": "false"}, {"axis": 1}, {"command_id": 204}, {"physics_mode": "invalid"}):
            with self.assertRaises(ValidationError):
                settings.SceneSettings.model_validate(data)

    def test_all_settings_preflight_before_any_mutation(self):
        reader = MagicMock()
        with patch.object(settings, "UIReader", return_value=reader), patch.object(settings, "context"), \
             patch.object(settings, "snapshot", return_value=({"axis": False, "mme_enabled": None},
                          {215: {"enabled": True}})), patch.object(settings, "_message") as message:
            with self.assertRaisesRegex(ValueError, "unavailable"):
                settings.set_settings({"axis": True, "mme_enabled": True}, 1)
            message.assert_not_called()

    def test_idempotent_patch_sends_no_command(self):
        with patch.object(settings, "UIReader"), patch.object(settings, "context"), \
             patch.object(settings, "snapshot", return_value=({"axis": True}, {215: {"enabled": True}})), \
             patch.object(settings, "_message") as message:
            result = settings.set_settings({"axis": True}, 1)
            self.assertEqual(result["applied"], [])
            message.assert_not_called()

    def test_failed_readback_is_not_success(self):
        with patch.object(settings, "UIReader"), patch.object(settings, "context"), \
             patch.object(settings, "snapshot", return_value=({"axis": False}, {215: {"enabled": True}})), \
             patch.object(settings, "menu_items", return_value={215: {"enabled": True}}), \
             patch.object(settings, "_message"):
            result = settings.set_settings({"axis": True}, 1)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["failed_setting"], "axis")


class ReleaseValidationTests(unittest.TestCase):
    def test_numeric_and_operation_constraints(self):
        cases = [(OutputSize, {"width": True, "height": 100}),
                 (OutputSize, {"width": 999999, "height": 100}),
                 (GravityValues, {"acceleration": float("nan")}),
                 (GravityValues, {"noise": False, "noise_amount": 3}),
                 (VideoOptions, {"start_frame": 10, "end_frame": 0}),
                 (PlaybackOptions, {"start_frame": 10, "end_frame": 0}),
                 (TransformSpec, {"operation": "lip_shift", "factor": 2}),
                 (TransformSpec, {"operation": "scale_time", "start_frame": 0, "end_frame": 10, "factor": 2, "tracks": ["bones", "bones"]})]
        for model, data in cases:
            with self.subTest(model=model.__name__, data=data), self.assertRaises(ValidationError):
                model.model_validate(data)

    def test_wrong_confirmation_with_same_title_is_not_accepted(self):
        dialog = {"title": "新規作成", "controls": [{"class": "Static", "text": "目のフレームを全て削除します"}]}
        with patch.object(lifecycle.dialogs, "wait_dialog", return_value=dialog), \
             patch.object(lifecycle.dialogs, "close") as close:
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                lifecycle.confirm(MagicMock(), "新規作成", "現在の状態は破棄されます\n\nよろしいですか？")
            close.assert_not_called()

    def test_new_scene_requires_explicit_discard(self):
        with patch.object(lifecycle, "UIReader") as reader:
            for value in (False, 1, "true", None):
                with self.assertRaises(ValueError):
                    lifecycle.new_project(value, 1)
            reader.assert_not_called()

    def test_nested_file_dialog_requires_exact_parent(self):
        with patch.object(files, "verify_process"), patch.object(files, "owned_dialogs", return_value=[]), \
             patch.object(files.win32gui, "PostMessage") as post:
            result = files.run_dialog_flow(MagicMock(), Path("C:/fixture.emm"), parent_dialog=(42, "エフェクトファイル割り当て"))
            self.assertEqual(result["status"], "verification_failed")
            post.assert_not_called()

    def test_motion_notice_is_not_mistaken_for_save_dialog(self):
        dialog = {"hwnd": 42, "title": "モーションデータ保存", "controls": [
            {"class": "Button", "id": 2, "text": "OK", "enabled": True}]}
        with patch.object(files, "verify_process"), patch.object(files, "owned_dialogs", return_value=[dialog]), \
             patch.object(files.win32gui, "PostMessage") as post:
            result = files.run_dialog_flow(MagicMock(), Path("C:/fixture.vmd"))
            self.assertEqual(result["status"], "dialog_requires_action")
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
