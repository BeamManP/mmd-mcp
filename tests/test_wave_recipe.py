"""Recipe math plus opt-in tests against a locally supplied licensed model.

Set MMD_WAVE_TEST_MODEL to the Tda V4X PMX for the build/trajectory tests.
No model or third-party animation is included in the test data.
"""
import copy
import importlib.util
import math
import os
from pathlib import Path
import tempfile
import unittest

from mmd_mcp.motion_document import vmd_bytes
from mmd_mcp.rotation import axis_angle

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/mmd-pose-motion/scripts/wave_recipe.py'
spec = importlib.util.spec_from_file_location('wave_recipe_tested', SCRIPT)
wave = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wave)


class WaveMathTests(unittest.TestCase):
    def test_linear_channel_keeps_constant_speed(self):
        for t in [0.,.01,.1,.4,.8,.999,1.]:
            self.assertAlmostEqual(wave.bezier_amount(t,wave.LINEAR),t,places=8)

    def test_slerp_uses_shortest_path_across_wraparound(self):
        a=axis_angle((0,0,1),350.);b=axis_angle((0,0,1),10.)
        mid=wave.slerp(a,b,.5)
        self.assertLess(wave.angular_distance(mid,(0,0,0,1)),1e-5)
        self.assertAlmostEqual(wave.angular_distance(a,mid),10.,places=6)

    def test_antipodal_quaternions_do_not_rotate(self):
        a=axis_angle((1,0,0),75.)
        mid=wave.slerp(a,tuple(-x for x in a),.5)
        self.assertLess(wave.angular_distance(a,mid),1e-5)

    def test_evaluate_uses_the_destination_curve_and_independent_channels(self):
        a={'frame':0,'position':{'x':0.,'y':0.,'z':0.},'quaternion_xyzw':(0,0,0,1),'interpolation':{k:wave.SMOOTH for k in ['x','y','z','rotation']}}
        b={'frame':10,'position':{'x':100.,'y':100.,'z':0.},'quaternion_xyzw':axis_angle((0,0,1),90.),'interpolation':{k:dict(wave.LINEAR) for k in ['x','y','z','rotation']}}
        b['interpolation']['x']={'x1':0,'y1':0,'x2':127,'y2':0}
        pos,q=wave.evaluate([a,b],5)
        self.assertAlmostEqual(pos['x'],12.5,places=6)
        self.assertAlmostEqual(pos['y'],50.,places=6)
        self.assertAlmostEqual(wave.angular_distance(a['quaternion_xyzw'],q),45.,places=6)

    def test_model_and_input_domain_are_enforced(self):
        r=wave.load_recipe();p={'model_sha256':r['model_sha256']}
        for count in [True,0,4,2.0]:
            with self.assertRaises(ValueError):wave.check_request(p,r,'quiet',count,'normal')
        with self.assertRaises(ValueError):wave.check_request({'model_sha256':'0'*64},r,'quiet',2,'normal')
        with self.assertRaises(ValueError):wave.check_request(p,r,'unknown',2,'normal')


@unittest.skipUnless(os.environ.get('MMD_WAVE_TEST_MODEL'),'Provide a local licensed PMX in MMD_WAVE_TEST_MODEL.')
class WaveModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile=wave.read_profile(str(Path(os.environ['MMD_WAVE_TEST_MODEL']).resolve()))

    def emitted(self,style='quiet',cycles=2,speed='normal'):
        doc,manifest=wave.build(self.profile,style,cycles,speed)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'motion.vmd';path.write_bytes(vmd_bytes(doc))
            rows=wave.read_records(path)
        return doc,manifest,rows

    def test_all_18_conditions_have_visible_round_trips_and_matching_end_pose(self):
        for style in ['quiet','broad']:
            for count in [1,2,3]:
                for speed in ['brisk','normal','slow']:
                    with self.subTest(style=style,count=count,speed=speed):
                        _,manifest,rows=self.emitted(style,count,speed)
                        result=wave.validate_records(self.profile,rows,manifest)
                        self.assertTrue(result['passed'],result['issues'])
                        self.assertEqual(result['observed_round_trips'],count)

    def test_movement_removed_from_clip_is_caught_despite_unchanged_manifest(self):
        _,manifest,rows=self.emitted()
        for key in rows:
            if key['track']=='bones' and key['name']=='右手首':key['quaternion_xyzw']=(0,0,0,1)
        result=wave.validate_records(self.profile,rows,manifest)
        self.assertIn('visible_round_trip_count_mismatch',result['issues'])
        self.assertIn('insufficient_visible_tip_span',result['issues'])

    def test_intermediate_foot_sliding_is_caught_even_when_end_pose_matches(self):
        _,manifest,rows=self.emitted()
        key=copy.deepcopy(next(k for k in rows if k['track']=='bones' and k['name']=='右足ＩＫ'))
        key['frame']=40;key['position']['x']=.25;rows.append(key)
        result=wave.validate_records(self.profile,rows,manifest)
        self.assertIn('static_support_or_torso_changed:右足ＩＫ',result['issues'])

    def test_exported_ik_off_is_not_mistaken_for_grounded_feet(self):
        _,manifest,rows=self.emitted()
        rows.append({'track':'model_flags','frame':0,'visible':True,'ik':[{'name':'右足ＩＫ','enabled':False}]})
        result=wave.validate_records(self.profile,rows,manifest)
        self.assertIn('foot_ik_disabled:右足ＩＫ',result['issues'])

    def test_broad_arm_does_not_raise_again_during_settle(self):
        _,manifest,rows=self.emitted('broad')
        tracks=wave.tracks_from_records(rows)
        start,end=manifest['phases']['settle']
        for name in ['右肩','右腕','右ひじ']:
            first=wave.evaluate(tracks[name],start)[1]
            for f in range(start,end+1):
                self.assertLess(wave.angular_distance(first,wave.evaluate(tracks[name],f)[1]),1e-4)

    def test_clip_length_and_initial_keys_are_checked(self):
        _,manifest,rows=self.emitted()
        rows=[k for k in rows if not (k['track']=='bones' and k['name']=='右手首' and k['frame']==0)]
        result=wave.validate_records(self.profile,rows,manifest)
        self.assertIn('missing_initial_key:右手首',result['issues'])
        manifest['last_frame']+=1
        result=wave.validate_records(self.profile,rows,manifest)
        self.assertIn('last_frame_mismatch',result['issues'])

    def test_same_request_produces_identical_vmd_bytes(self):
        a,ma=wave.build(self.profile,'broad',3,'brisk')
        b,mb=wave.build(self.profile,'broad',3,'brisk')
        self.assertEqual(vmd_bytes(a),vmd_bytes(b))
        self.assertEqual(ma,mb)


if __name__=='__main__':unittest.main()
