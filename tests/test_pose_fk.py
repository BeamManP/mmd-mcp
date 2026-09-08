import math
import unittest

from mmd_mcp import pose_fk


def profile(arm_down=True):
    """Tiny right-arm chain: shoulder at origin, arm out along -X and down 37.5 degrees like an A-pose."""
    d = math.radians(37.5)
    step = (-math.cos(d) * 2.5, -math.sin(d) * 2.5, 0.)
    names = ['頭', '右肩', '右腕', '右ひじ', '右手捩', '右手首', '右中指１', '右中指２', '右人指１', '右小指１']
    pos = {'頭': (0., 17.2, 0.), '右肩': (-0.2, 16.2, 0.)}
    pos['右腕'] = (-1.0, 16.0, 0.)
    pos['右ひじ'] = tuple(a + b for a, b in zip(pos['右腕'], step))
    pos['右手捩'] = tuple(a + b / 2 for a, b in zip(pos['右ひじ'], step))
    pos['右手首'] = tuple(a + b for a, b in zip(pos['右ひじ'], step))
    pos['右中指１'] = tuple(a + b * .3 for a, b in zip(pos['右手首'], step))
    pos['右中指２'] = tuple(a + b * .5 for a, b in zip(pos['右手首'], step))
    pos['右人指１'] = tuple(a + b for a, b in zip(pos['右中指１'], (0., 0., -.3)))
    pos['右小指１'] = tuple(a + b for a, b in zip(pos['右中指１'], (0., 0., .3)))
    return {'bones': [{'name': n, 'rest_position': list(pos[n])} for n in names]}


class PoseFKTests(unittest.TestCase):
    def test_rest_pose_keeps_rest_positions_and_palm(self):
        chain = pose_fk.arm_chain(profile(), '右')
        r = pose_fk.evaluate_arm(chain, '右', {})
        rest = chain['rest']
        for axis in range(3):
            self.assertAlmostEqual(r['wrist'][axis], rest['右手首'][axis], places=6)
        self.assertAlmostEqual(sum(c * c for c in r['palm_normal']), 1., places=6)

    def test_lifting_the_arm_raises_the_wrist(self):
        chain = pose_fk.arm_chain(profile(), '右')
        down = pose_fk.evaluate_arm(chain, '右', {})['wrist'][1]
        up = pose_fk.evaluate_arm(chain, '右', {'右腕': (0., 0., 60.)})['wrist'][1]
        self.assertGreater(up, down)

    def test_missing_chain_is_reported(self):
        with self.assertRaisesRegex(ValueError, 'lacks arm bones'):
            pose_fk.arm_chain({'bones': [{'name': '頭', 'rest_position': [0, 17, 0]}]}, '右')

    def test_wrist_turn_search_finds_the_best_alignment(self):
        def compile_arm(turn):
            rad = math.radians(turn)
            return {'palm_normal': (0., math.sin(rad), -math.cos(rad))}
        turn, score = pose_fk.solve_wrist_turn(compile_arm, (0., 0., -1.))
        self.assertAlmostEqual(turn, 0., delta=1.)
        self.assertGreater(score, .999)

    def test_hand_position_search_hits_height_and_side(self):
        def compile_arm(lift, bend):
            # a fake reach: wrist rises with lift, moves inward with bend
            return {'wrist': (-3. + bend / 100., 15. + lift / 20., 0.), 'wrist_above_head': (15. + lift / 20.) - 17.2}
        lift, bend, cost = pose_fk.solve_hand_position(compile_arm, .9, 2.4, -1., 0.)
        self.assertAlmostEqual(15. + lift / 20. - 17.2, .9, delta=.3)
        self.assertLess(cost, 1.)

    def test_describe_labels_camera_facing_palm(self):
        d = pose_fk.describe({'palm_normal': (0., 0., -1.), 'wrist_above_head': .95})
        self.assertEqual((d['palm_facing'], d['hand_level']), ('camera', 'ear'))


if __name__ == '__main__':
    unittest.main()
