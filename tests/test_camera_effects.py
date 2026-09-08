import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from mmd_mcp import camera_batch as cb, effects
from mmd_mcp.bone_controls import AxisValues


class CameraBatchTests(unittest.TestCase):
    def test_frame_needs_values(self):
        with self.assertRaises(ValidationError):
            cb.CameraFrame(frame=0)
        with self.assertRaises(ValidationError):
            cb.CameraFrame(frame=0, camera=cb.CameraValues())
        item = cb.CameraFrame(frame=0, camera=cb.CameraValues(distance=40., position=AxisValues(y=10.)),
                              light={'color': {'r': 154}})
        self.assertEqual(item.camera.updates(), [(545, 10.), (550, 40.)])
        self.assertEqual(item.light.updates(), [(461, 154)])

    def test_frames_ascend_and_register_buttons_pressed(self):
        reader = MagicMock()
        frames, clicks = [], []
        with patch.object(cb, 'UIReader', return_value=reader), \
             patch.object(cb.scene, 'context', side_effect=lambda _r, _m: (str(frames[-1] if frames else 0), 0, 'cam')), \
             patch.object(cb.scene, 'commit_number', side_effect=lambda _r, _c, v: frames.append(v)), \
             patch.object(cb.scene, 'apply_fields'), patch.object(cb.scene, 'numbers', side_effect=lambda _r, f: {k: 40. if k == 550 else 154. for k in f}), \
             patch.object(cb.scene, 'click_button', side_effect=lambda _r, cid: clicks.append(cid)):
            result = cb.batch_camera_keys([
                cb.CameraFrame(frame=30, camera=cb.CameraValues(distance=40.)),
                cb.CameraFrame(frame=0, light={'color': {'r': 154}}, register_key=False),
            ], hwnd=1)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(frames, [0, 30, 0])
        self.assertEqual(clicks, [452])

    def test_readback_mismatch_stops_with_progress(self):
        reader = MagicMock()
        with patch.object(cb, 'UIReader', return_value=reader), \
             patch.object(cb.scene, 'context', return_value=('5', 0, 'cam')), patch.object(cb.scene, 'commit_number'), \
             patch.object(cb.scene, 'apply_fields'), patch.object(cb.scene, 'numbers', return_value={550: 1.}), \
             patch.object(cb.scene, 'click_button') as click:
            result = cb.batch_camera_keys([cb.CameraFrame(frame=5, camera=cb.CameraValues(distance=40.))], hwnd=1)
        self.assertEqual(result['status'], 'incomplete')
        click.assert_not_called()


EMM = """[Info]
Version = 3

[Object]
Pmd1 = UserFile\\Model\\miku.pmx
Acs1 = UserFile\\MME\\AutoLuminous4\\AutoLuminous.x

[Effect]
Default = none
Pmd1 = none
Acs1 = UserFile\\MME\\AutoLuminous4\\AutoLuminous.fx
"""


class EffectsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / 'scene.emm'
        self.path.write_bytes(EMM.encode('cp932'))

    def tearDown(self):
        self.dir.cleanup()

    def test_read_reports_objects_and_effects(self):
        result = effects.read_emm(str(self.path))
        self.assertEqual(result['version'], '3')
        self.assertEqual(set(result['objects']), {'Pmd1', 'Acs1'})
        self.assertIsNone(result['effects']['Pmd1'])
        self.assertTrue(result['effects']['Acs1'].endswith('AutoLuminous.fx'))

    def test_write_updates_only_known_keys_and_preserves_sections(self):
        fx = Path(self.dir.name) / 'glow.fx'
        fx.write_text('// fx')
        result = effects.write_emm(str(self.path), {'Pmd1': str(fx), 'Acs1': None, 'Pmd1[2]': str(fx)})
        self.assertEqual(set(result['changed']), {'Pmd1', 'Acs1', 'Pmd1[2]'})
        again = effects.read_emm(str(self.path))
        self.assertEqual(again['effects']['Pmd1'], str(fx))
        self.assertIsNone(again['effects']['Acs1'])
        self.assertEqual(again['effects']['Pmd1[2]'], str(fx))
        self.assertEqual(again['objects']['Pmd1'], 'UserFile\\Model\\miku.pmx')
        for bad in ({'Acs9': None}, {'Pmd1': str(Path(self.dir.name) / 'missing.fx')}, {'Pmd1': 'notes.txt'}, {}):
            with self.assertRaises(ValueError):
                effects.write_emm(str(self.path), bad)
        with self.assertRaises(ValueError):
            effects.write_emm(str(self.path), {'Pmd1': None}, create_from_pmm='C:/x.pmm')


if __name__ == '__main__':
    unittest.main()
