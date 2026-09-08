import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from mmd_mcp import scene_controls as scene
from mmd_mcp.bone_controls import AxisValues


class SceneTests(unittest.TestCase):
    def test_names_require_unambiguous_match(self):
        self.assertEqual(scene.resolve_index(["camera", "Miku"], None, "Miku"), 1)
        for index, name in ((None, "Miku"), (None, "missing"), (True, None), (3, None), (0, "Miku")):
            with self.assertRaises(ValueError):
                scene.resolve_index(["Miku", "Miku"], index, name)

    def test_light_range_and_type_validation(self):
        for kwargs in ({"r": -1}, {"g": 256}, {"r": True}, {"r": 10.5}):
            with self.assertRaises(ValidationError):
                scene.RGBValues(**kwargs)
        for kwargs in ({"x": 1.01}, {"y": float("nan")}, {"z": True}):
            with self.assertRaises(ValidationError):
                scene.DirectionValues(**kwargs)

    def test_zero_direction_is_rejected_before_any_edit(self):
        state = {"direction": {"x": 0, "y": -1, "z": 0}}
        with patch.object(scene, "UIReader"), patch.object(scene, "context"), \
             patch.object(scene, "panel_state", return_value=state), \
             patch.object(scene, "apply_fields") as apply:
            with self.assertRaisesRegex(ValueError, "zero vector"):
                scene.set_light(direction=scene.DirectionValues(y=0))
            apply.assert_not_called()

    def test_arbitrary_numeric_controls_and_actions_are_rejected(self):
        for operation, control in ((scene.commit_number, 500), (scene.click_button, 208)):
            with self.assertRaises(ValueError), patch.object(scene, "_message") as native:
                if operation is scene.commit_number:
                    operation(MagicMock(), control, 10)
                else:
                    operation(MagicMock(), control)
            native.assert_not_called()

    def test_partial_edit_reports_completed_controls(self):
        reader = MagicMock()
        with patch.object(scene, "commit_number", side_effect=[None, RuntimeError("timeout")]):
            with self.assertRaisesRegex(RuntimeError, r"Completed controls: \[544\].*Partial changes"):
                scene.apply_fields(reader, ("0", 0, "camera"), [(544, 1), (545, 2)])

    def test_mutation_lock_is_released_on_failure(self):
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            with scene.mutation():
                with self.assertRaisesRegex(RuntimeError, "in progress"):
                    with scene.mutation():
                        pass
                raise RuntimeError("fixture")
        with scene.mutation():
            pass

    def test_camera_edits_keep_omitted_fields_out_of_writes(self):
        reader = MagicMock()
        with patch.object(scene, "UIReader", return_value=reader), patch.object(scene, "context"), \
             patch.object(scene, "panel_state", return_value={"perspective": True}), \
             patch.object(scene, "apply_fields", return_value=[544]) as apply:
            scene.set_camera(position=AxisValues(x=2))
            self.assertEqual(apply.call_args.args[2], [(544, 2)])


if __name__ == "__main__":
    unittest.main()
