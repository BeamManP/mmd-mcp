"""Model-bound semantic pose compilation. No live MMD imports are performed."""
import hashlib
import math
from pathlib import Path
from typing import Annotated, Literal
from pydantic import Field
from .motion_document import Strict, Vector, BoneKey
from .rotation import axis_angle, multiply, to_ui
from . import pose_fk

MIKU_SHA256 = 'eccc4952b8c28695117b6e7edd9f8de960d6645f2b550ccd027f4f257ac27f90'
MEIKO_SHA256 = '204653122c85cf1ab6f822c67954fc42ad5f247dff4ce4264245cba4fb135c7e'
TDA_SHA256 = 'a3876a152b456d4d4e99b2b8fbb7d87c5308c0ad0c624b3163a7dc84dcbaca77'
PROFILES = {MIKU_SHA256: 'animasa_miku_1_3', MEIKO_SHA256: 'animasa_meiko', TDA_SHA256: 'tda_miku_v4x_1_00'}


def difference(a, b):
    return tuple(x-y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def read_profile(model_path, bone_name=None, bone_index=None):
    path = Path(model_path)
    if not path.is_absolute() or path.suffix.lower() not in {'.pmd', '.pmx'} or path.stat().st_size > 128*1024*1024:
        raise ValueError('Provide an absolute PMD/PMX model path under 128 MiB.')
    data = path.read_bytes()
    if path.suffix.lower() == '.pmx':
        from .pmx_geometry import read_pmx_geometry
        model_name, bones = read_pmx_geometry(data)
    else:
        from .pmd_geometry import read_pmd_geometry
        model_name, bones = read_pmd_geometry(data)
    from .model_inspection import inspect_skeleton
    investigation = inspect_skeleton(bones, path.suffix.lower()[1:], bone_name, bone_index)
    digest = hashlib.sha256(data).hexdigest()
    return {'model_path': str(path), 'model_name': model_name,
            'model_sha256': digest, 'bones': bones,
            'semantic_profile': PROFILES.get(digest),
            'investigation': investigation,
            'limitations': ['Semantic controls are calibrated only for the exact profiled Animasa Miku 1.3, MEIKO and Tda Miku V4X 1.00 model files.',
                           'Live matching checks bone names/order; the loaded file digest cannot be proven from the UI.']}


Angle = Annotated[float, Field(allow_inf_nan=False, ge=-180, le=180)]


class ArmPose(Strict):
    shoulder_lift: Angle = 0.
    arm_lift: Angle = 0.
    arm_forward: Angle = 0.
    elbow_bend: Annotated[float, Field(allow_inf_nan=False, ge=0, le=150)] = 0.
    wrist_turn: Angle = 0.
    wrist_tilt: Angle = 0.
    gesture: Literal['relaxed', 'open', 'peace', 'fist'] = 'relaxed'
    finger_spread: Annotated[float, Field(allow_inf_nan=False, ge=0, le=30)] = 8.
    # Goals solved by forward kinematics on the calibrated model; they override the numeric fields above.
    hand_at: Literal['ear', 'shoulder', 'chest', 'overhead'] | None = None
    palm_facing: Literal['camera', 'up', 'down'] | None = None


class SemanticPose(Strict):
    center: Vector = Field(default_factory=Vector)
    body_lean: Angle = 0.
    body_turn: Angle = 0.
    body_bow: Angle = 0.
    head_tilt: Angle = 0.
    head_turn: Angle = 0.
    head_nod: Angle = 0.
    left_arm: ArmPose = Field(default_factory=ArmPose)
    right_arm: ArmPose = Field(default_factory=ArmPose)
    left_foot: Vector = Field(default_factory=Vector)
    right_foot: Vector = Field(default_factory=Vector)


def compile_pose(model_path, pose, frame=0):
    return compile_with_profile(read_profile(model_path), pose, frame)


def resolve_goals(profile, pose):
    """Replace hand_at / palm_facing goals with numeric arm fields found by FK search."""
    if not any(getattr(arm, g) for arm in (pose.left_arm, pose.right_arm) for g in ('hand_at', 'palm_facing')):
        return pose, {}
    solved = pose.model_copy(deep=True)
    report = {}
    for attr, side in (('left_arm', '左'), ('right_arm', '右')):
        arm = getattr(solved, attr)
        if not (arm.hand_at or arm.palm_facing):
            continue
        chain = pose_fk.arm_chain(profile, side)
        def evaluate(candidate):
            trial = solved.model_copy(deep=True)
            setattr(trial, attr, candidate)
            keys = compile_with_profile(profile, trial, 0, solve=False)['bones']
            rotations = {k['name']: (k['rotation_degrees']['x'], k['rotation_degrees']['y'], k['rotation_degrees']['z']) for k in keys}
            return pose_fk.evaluate_arm(chain, side, rotations)
        entry = {}
        if arm.hand_at:
            lift, bend, cost = pose_fk.solve_hand_position(
                lambda l, b: evaluate(arm.model_copy(update={'arm_lift': l, 'elbow_bend': b, 'hand_at': None, 'palm_facing': None})),
                pose_fk.HAND_HEIGHTS[arm.hand_at], pose_fk.HAND_LATERAL[arm.hand_at], chain['sign'], pose_fk.HAND_DEPTH[arm.hand_at])
            arm = arm.model_copy(update={'arm_lift': lift, 'elbow_bend': bend})
            entry['hand_at'] = {'goal': solved.__getattribute__(attr).hand_at, 'arm_lift': lift, 'elbow_bend': bend, 'residual': round(cost, 3)}
        if arm.palm_facing:
            direction = pose_fk.DIRECTIONS[arm.palm_facing]
            turn, score = pose_fk.solve_wrist_turn(
                lambda t: evaluate(arm.model_copy(update={'wrist_turn': t, 'hand_at': None, 'palm_facing': None})), direction)
            arm = arm.model_copy(update={'wrist_turn': turn})
            entry['palm_facing'] = {'goal': arm.palm_facing, 'wrist_turn': turn, 'alignment': round(score, 3)}
        setattr(solved, attr, arm.model_copy(update={'hand_at': None, 'palm_facing': None}))
        report[attr] = entry
    return solved, report


def fk_summary(profile, keys):
    """Per-arm FK description for compiled keys, when the model exposes the arm chain."""
    rotations = {k['name']: (k['rotation_degrees']['x'], k['rotation_degrees']['y'], k['rotation_degrees']['z']) for k in keys}
    summary = {}
    for attr, side in (('left_arm', '左'), ('right_arm', '右')):
        try:
            chain = pose_fk.arm_chain(profile, side)
        except ValueError:
            continue
        result = pose_fk.evaluate_arm(chain, side, rotations)
        summary[attr] = {**pose_fk.describe(result), 'wrist': [round(c, 2) for c in result['wrist']],
                         'palm_normal': [round(c, 2) for c in result['palm_normal']]}
    return summary


def compile_with_profile(profile, pose, frame=0, solve=True):
    if profile['semantic_profile'] is None:
        raise ValueError('This model has no calibrated semantic profile. Use explicit named bone transforms.')
    goals = {}
    if solve:
        pose, goals = resolve_goals(profile, pose)
    tda = profile['model_sha256'] == TDA_SHA256
    keys = []
    def add(name, x=0., y=0., z=0., position=None):
        keys.append(BoneKey(name=name, frame=frame, position=position or Vector(),
                            rotation_degrees=Vector(x=x, y=y, z=z)))
    add('センター', position=pose.center)
    if tda:
        add('上半身', pose.body_bow*.45, pose.body_turn*.45, pose.body_lean*.45)
        add('上半身2', pose.body_bow*.55, pose.body_turn*.55, pose.body_lean*.55)
    else:
        add('上半身', pose.body_bow, pose.body_turn, pose.body_lean)
    add('頭', pose.head_nod, pose.head_turn, pose.head_tilt)
    add('左足ＩＫ', position=pose.left_foot)
    add('右足ＩＫ', position=pose.right_foot)
    for side, sign, arm in [('左', 1., pose.left_arm), ('右', -1., pose.right_arm)]:
        add(side+'肩', z=-sign*arm.shoulder_lift)
        add(side+'腕', y=sign*arm.arm_forward, z=-sign*arm.arm_lift)
        add(side+'ひじ', z=-sign*arm.elbow_bend)
        # PMD fingers have no per-bone local-axis metadata. Derive axes from rest
        # geometry for this calibrated model, rather than guessing Euler signs.
        rest = {b['name']: b['rest_position'] for b in profile['bones']}
        forearm_axis = difference(rest[side+'手首'], rest[side+'ひじ'])
        if tda:
            add(side+'手捩', *to_ui(axis_angle(forearm_axis, sign*arm.wrist_turn)))
            wrist = axis_angle((0, 0, 1), sign*arm.wrist_tilt)
            add(side+'親指０')
        else:
            wrist = multiply(axis_angle(forearm_axis, sign*arm.wrist_turn),
                             axis_angle((0, 0, 1), sign*arm.wrist_tilt))
        add(side+'手首', *to_ui(wrist))
        long_axis = difference(rest[side+'中指２'], rest[side+'中指１'])
        breadth = difference(rest[side+'小指１'], rest[side+'人指１'])
        palm_normal = tuple(sign*v for v in cross(long_axis, breadth))
        for finger in ['人指', '中指', '薬指', '小指']:
            direction = difference(rest[side+finger+'２'], rest[side+finger+'１'])
            curl_axis = cross(direction, palm_normal)
            curl = 0. if arm.gesture == 'open' or (arm.gesture == 'peace' and finger in ['人指', '中指']) else (12. if arm.gesture == 'relaxed' else 85.)
            spread = (-arm.finger_spread if finger == '人指' else arm.finger_spread) if arm.gesture == 'peace' and finger in ['人指', '中指'] else 0.
            for segment in ['１', '２', '３']:
                q = axis_angle(curl_axis, curl)
                if segment == '１' and spread:
                    q = multiply(axis_angle(palm_normal, spread), q)
                add(side+finger+segment, *to_ui(q))
        for segment in ['１', '２']:
            direction = difference(rest[side+'親指２'], rest[side+'親指１'])
            curl_axis = cross(direction, palm_normal)
            curl = (55. if segment == '１' else 65.) if arm.gesture in ['peace', 'fist'] else 5.
            add(side+'親指'+segment, *to_ui(axis_angle(curl_axis, curl)))
    bones = [k.model_dump() for k in keys]
    result = {'profile': {k: v for k, v in profile.items() if k != 'bones'},
              'bones': bones, 'keyframes_registered': False,
              'note': 'Absolute pose for listed bones only; unlisted bones, morphs and IK switches are preserved.'}
    if solve:
        result['fk'] = fk_summary(profile, bones)
        if goals:
            result['solved_goals'] = goals
    return result
