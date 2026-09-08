"""Opt-in emitted-trajectory tests using a locally supplied licensed Tda PMX."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'skills/mmd-pose-motion/scripts/inertia_recipe.py'
spec=importlib.util.spec_from_file_location('inertia_recipe_tested',SCRIPT)
recipe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)


@unittest.skipUnless(os.environ.get('MMD_INERTIA_TEST_MODEL'),'Provide local licensed PMX in MMD_INERTIA_TEST_MODEL.')
class InertiaRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=Path(os.environ['MMD_INERTIA_TEST_MODEL']).resolve()
        cls.profile=recipe.read_profile(str(cls.model))
        cls.temp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.outputs={}
        for kind,lag in [('jump',True),('joy',True),('joy',False)]:
            out=recipe.build(cls.model,Path(cls.temp.name)/(kind+str(lag)),kind,lag)
            cls.outputs[kind,lag]=(recipe.w.read_records(out/'motion.vmd'),json.loads((out/'manifest.json').read_text(encoding='utf8')),out)

    def test_emitted_clips_preserve_air_acceleration_reach_and_ground_support(self):
        for records,manifest,_ in self.outputs.values():
            result=recipe.validate_records(records,manifest,self.profile)
            self.assertTrue(result['passed'],result['errors'])

    def test_non_ballistic_air_and_floating_support_fail_independently(self):
        records,manifest,_=self.outputs['jump',True]
        changed=copy.deepcopy(records)
        next(r for r in changed if r['track']=='bones' and r['name']=='センター' and r['frame']==36)['position']['y']+=.5
        self.assertIn('air_acceleration',recipe.validate_records(changed,manifest,self.profile)['errors'])
        changed=copy.deepcopy(records)
        next(r for r in changed if r['track']=='bones' and r['name']=='右足ＩＫ' and r['frame']==0)['position']['y']=.3
        self.assertTrue(any(e.startswith('foot_support_or_air') for e in recipe.validate_records(changed,manifest,self.profile)['errors']))

    def test_disabling_ik_is_not_mistaken_for_a_valid_foot_target(self):
        records,manifest,_=self.outputs['joy',True]
        changed=copy.deepcopy(records)
        next(r for r in changed if r['track']=='model_flags')['ik'][0]['enabled']=False
        self.assertIn('ik_disabled:右足ＩＫ',recipe.validate_records(changed,manifest,self.profile)['errors'])

    def test_lag_changes_upper_chain_without_changing_flight_or_final_pose(self):
        a,manifest,_=self.outputs['joy',True];b,_,_=self.outputs['joy',False]
        a=recipe.w.tracks_from_records(a);b=recipe.w.tracks_from_records(b)
        for n in ['センター','右足ＩＫ','左足ＩＫ']:
            self.assertEqual(a[n],b[n])
        q1=recipe.w.evaluate(a['右ひじ'],28)[1];q2=recipe.w.evaluate(b['右ひじ'],28)[1]
        self.assertGreater(recipe.w.angular_distance(q1,q2),3.)
        for n in a:
            q1=recipe.w.evaluate(a[n],manifest['last_frame'])[1];q2=recipe.w.evaluate(b[n],manifest['last_frame'])[1]
            self.assertLess(recipe.w.angular_distance(q1,q2),.002)

    def test_existing_output_and_unknown_action_do_not_overwrite(self):
        _,_,out=self.outputs['joy',True];before=(out/'motion.vmd').read_bytes()
        with self.assertRaises(FileExistsError):recipe.build(self.model,out,'joy')
        self.assertEqual((out/'motion.vmd').read_bytes(),before)
        bad=Path(self.temp.name)/'invalid'
        with self.assertRaises(ValueError):recipe.build(self.model,bad,'unknown')
        self.assertFalse(bad.exists())


if __name__=='__main__':unittest.main()
