"""Forward kinematics for the calibrated arm chain, and goal solving on top of it.

Positions are in MMD world units at rest, with the model's rest orientation:
+X = model's left, +Y = up, -Z = toward the default camera. Bone UI angles are
converted with rotation.from_ui and applied in the parent's frame, which matched
captures on the Tda model (2026-09-07).
"""
import math

from .rotation import from_ui, multiply

DIRECTIONS = {'camera': (0., 0., -1.), 'up': (0., 1., 0.), 'down': (0., -1., 0.)}
HAND_HEIGHTS = {'ear': .9, 'shoulder': -1.2, 'chest': -3.5, 'overhead': 2.5}  # wrist y minus head bone y
HAND_LATERAL = {'ear': 3.0, 'shoulder': 3.0, 'chest': 1.2, 'overhead': 1.0}  # wrist |x| offset to the arm's side
HAND_DEPTH = {'ear': -.6, 'shoulder': -.8, 'chest': -1.5, 'overhead': -.3}  # wrist z (negative = toward camera)
CHAIN = ('肩', '腕', 'ひじ', '手捩', '手首')


def rotate(q, p):
    x, y, z, w = q
    qv = (x, y, z)
    def cross(a, b):
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    t = tuple(2*c for c in cross(qv, p))
    return tuple(p[i] + w*t[i] + cross(qv, t)[i] for i in range(3))


def unit(v):
    n = math.sqrt(sum(c*c for c in v))
    if not n:
        raise ValueError('Zero-length vector.')
    return tuple(c/n for c in v)


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def rest_palm_normal(rest, side, sign):
    long_axis = sub(rest[side+'中指２'], rest[side+'中指１'])
    breadth = sub(rest[side+'小指１'], rest[side+'人指１'])
    l, b = long_axis, breadth
    normal = (l[1]*b[2]-l[2]*b[1], l[2]*b[0]-l[0]*b[2], l[0]*b[1]-l[1]*b[0])
    return unit(tuple(sign*c for c in normal))


def arm_chain(profile, side):
    """Return rest positions for one side's chain plus head height and palm normal."""
    rest = {b['name']: tuple(b['rest_position']) for b in profile['bones']}
    sign = 1. if side == '左' else -1.
    missing = [side+n for n in CHAIN if side+n not in rest]
    if missing:
        raise ValueError(f'Model lacks arm bones for FK: {missing}')
    return {'rest': rest, 'sign': sign, 'head_y': rest['頭'][1],
            'palm': rest_palm_normal(rest, side, sign),
            'finger': unit(sub(rest[side+'中指２'], rest[side+'中指１']))}


def evaluate_arm(chain, side, rotations):
    """rotations: {bone name: (x, y, z) UI degrees}. Returns wrist/fingertip positions and palm normal."""
    rest = chain['rest']
    def ui(name):
        return rotations.get(side+name, (0., 0., 0.))
    q_shoulder = from_ui(*ui('肩'))
    q_arm = multiply(q_shoulder, from_ui(*ui('腕')))
    q_elbow = multiply(q_arm, from_ui(*ui('ひじ')))
    q_hand = multiply(multiply(q_elbow, from_ui(*ui('手捩'))), from_ui(*ui('手首')))
    shoulder = rest[side+'肩']
    arm = tuple(a+b for a, b in zip(shoulder, rotate(q_shoulder, sub(rest[side+'腕'], shoulder))))
    elbow = tuple(a+b for a, b in zip(arm, rotate(q_arm, sub(rest[side+'ひじ'], rest[side+'腕']))))
    wrist = tuple(a+b for a, b in zip(elbow, rotate(q_elbow, sub(rest[side+'手首'], rest[side+'ひじ']))))
    tip = tuple(a+b for a, b in zip(wrist, rotate(q_hand, sub(rest[side+'中指２'], rest[side+'手首']))))
    palm = rotate(q_hand, chain['palm'])
    return {'elbow': elbow, 'wrist': wrist, 'fingertip': tip, 'palm_normal': palm,
            'finger_direction': rotate(q_hand, chain['finger']),
            'wrist_above_head': wrist[1] - chain['head_y']}


def describe(result):
    """Human-readable summary of an evaluate_arm result."""
    palm = result['palm_normal']
    facing = max(DIRECTIONS, key=lambda k: sum(a*b for a, b in zip(DIRECTIONS[k], palm)))
    height = result['wrist_above_head']
    level = min(HAND_HEIGHTS, key=lambda k: abs(HAND_HEIGHTS[k] - height))
    return {'palm_facing': facing, 'palm_camera_dot': round(-palm[2], 3), 'hand_level': level,
            'wrist_above_head': round(height, 2)}


def solve_wrist_turn(compile_arm, direction):
    """1-D search of wrist_turn (degrees) maximising palm normal · direction. compile_arm(turn) -> evaluate_arm result."""
    target = unit(direction)
    best = None
    for turn in range(-180, 181, 5):
        palm = compile_arm(float(turn))['palm_normal']
        score = sum(a*b for a, b in zip(palm, target))
        if best is None or score > best[0]:
            best = (score, float(turn))
    score, coarse = best
    for turn in [coarse + d for d in (-4, -3, -2, -1, 1, 2, 3, 4)]:
        palm = compile_arm(turn)['palm_normal']
        s = sum(a*b for a, b in zip(palm, target))
        if s > score:
            score, coarse = s, turn
    return coarse, score


def solve_hand_position(compile_arm, target_above_head, target_lateral, sign, target_depth=0., lift_range=(-45., 95.), bend_range=(5., 140.)):
    """Grid search of (arm_lift, elbow_bend) so the wrist sits at the target height above the head
    bone and at the target sideways offset on the arm's side (sign: +1 left arm, -1 right arm),
    staying near the frontal plane. compile_arm(lift, bend) -> evaluate_arm result."""
    best = None
    for lift in range(int(lift_range[0]), int(lift_range[1]) + 1, 5):
        for bend in range(int(bend_range[0]), int(bend_range[1]) + 1, 5):
            r = compile_arm(float(lift), float(bend))
            wx, _, wz = r['wrist']
            cost = (abs(r['wrist_above_head'] - target_above_head)
                    + .6 * abs(wx - sign * target_lateral) + .4 * abs(wz - target_depth))
            if best is None or cost < best[0]:
                best = (cost, float(lift), float(bend))
    return best[1], best[2], best[0]
