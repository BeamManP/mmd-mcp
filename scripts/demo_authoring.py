"""Build a reproducible Tda V4X peace demo; optional explicit live application.

Use an otherwise empty test model (no existing animation keys). The script writes
new files only and never launches, closes or selects a different MMD window.
"""
import argparse
import json
import time
from pathlib import Path

from mmd_mcp.pose_authoring import SemanticPose, ArmPose, compile_pose, read_profile, TDA_SHA256
from mmd_mcp.motion_document import (MotionDocument, BoneKey, MorphKey, Vector, Curve,
                                     Interpolation, KeyEdit, edit_document, save_document)


def documents(model_path):
    profile = read_profile(model_path)
    if profile['model_sha256'] != TDA_SHA256:
        raise ValueError('This calibrated demo requires the exact Tda Miku V4X 1.00 model.')
    final = SemanticPose(body_lean=-4., body_turn=-5., head_tilt=8., head_nod=-3.,
        left_arm=ArmPose(shoulder_lift=4., arm_lift=25., elbow_bend=105., wrist_turn=90.,
                         gesture='peace', finger_spread=15.),
        right_arm=ArmPose(arm_lift=-22., elbow_bend=12.),
        left_foot=Vector(x=.4), right_foot=Vector(x=-.2))
    neutral = final.model_copy(deep=True)
    neutral.body_lean = neutral.body_turn = neutral.head_tilt = neutral.head_nod = 0.
    neutral.left_arm = ArmPose(arm_lift=-25., elbow_bend=10.)
    morph_values = {'AL未使用': 1., 'にこり': .45, 'にっこり': .75, '笑い': .75}

    def keys(pose, frame):
        return [BoneKey.model_validate(k) for k in compile_pose(model_path, pose, frame)['bones']]
    static = MotionDocument(model_name=profile['model_name'], model_sha256=profile['model_sha256'],
        bones=keys(final, 0), morphs=[MorphKey(name=n, frame=0, weight=v) for n, v in morph_values.items()])
    baseline = MotionDocument(model_name=profile['model_name'], model_sha256=profile['model_sha256'],
        bones=keys(neutral, 0)+keys(final, 42)+keys(final, 150),
        morphs=[MorphKey(name=n, frame=f, weight=v if f or n == 'AL未使用' else 0.)
                for f in [0, 42, 150] for n, v in morph_values.items()])

    anticipation = neutral.model_copy(deep=True)
    anticipation.center.y = -.15
    anticipation.body_bow = 5.
    anticipation.head_nod = 3.
    passing = final.model_copy(deep=True)
    passing.body_lean = -2.
    passing.left_arm.elbow_bend = 65.
    passing.left_arm.wrist_turn = 45.
    passing.left_arm.gesture = 'relaxed'
    overshoot = final.model_copy(deep=True)
    overshoot.left_arm.arm_lift = 30.
    overshoot.left_arm.elbow_bend = 110.
    overshoot.head_tilt = 6.
    settling = final.model_copy(deep=True)
    settling.left_arm.arm_lift = 27.
    settling.head_tilt = 10.
    breathing = final.model_copy(deep=True)
    breathing.body_bow = 1.
    breathing.head_tilt = 7.
    edits = []
    ease = Interpolation(x=Curve(x1=35, y1=0, x2=95, y2=127),
                         y=Curve(x1=35, y1=0, x2=95, y2=127),
                         z=Curve(x1=35, y1=0, x2=95, y2=127),
                         rotation=Curve(x1=35, y1=0, x2=95, y2=127))
    for frame, pose in [(12, anticipation), (28, passing), (42, overshoot),
                        (48, settling), (60, final), (90, breathing), (120, final), (150, final)]:
        for key in keys(pose, frame):
            key.interpolation = ease.model_copy(deep=True)
            edits.append(KeyEdit(action='upsert_bone', name=key.name, frame=frame, bone=key))
    for name, value in morph_values.items():
        for frame, factor in [(12, 0.), (28, .35), (42, 1.), (60, 1.), (150, 1.)]:
            key = MorphKey(name=name, frame=frame, weight=value if name == 'AL未使用' else value*factor)
            edits.append(KeyEdit(action='upsert_morph', name=name, frame=frame, morph=key))
    refined = edit_document(baseline, edits)
    return static, baseline, refined, final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hwnd', type=int)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--preview-step', type=int, default=3)
    args = parser.parse_args()
    if not args.output.is_absolute():
        parser.error('--output must be an absolute new directory.')
    if args.apply and args.hwnd is None:
        parser.error('--apply requires the explicit HWND of a disposable test scene.')
    static, baseline, refined, pose = documents(args.model)
    args.output.mkdir(exist_ok=False)
    for name, doc in [('static', static), ('baseline', baseline), ('refined', refined)]:
        for kind in ['json', 'vmd']:
            save_document(doc, str(args.output/f'{name}.{kind}'), kind)
    (args.output/'semantic-pose.json').write_text(pose.model_dump_json(indent=2), encoding='utf-8')
    report = {'model_sha256': refined.model_sha256, 'model_credit': 'Tda / Hatsune Miku V4X Ver1.00',
              'frames': [0, 150], 'fps': 30,
              'baseline_keys': len(baseline.bones), 'refined_keys': len(refined.bones),
              'baseline_key_identities_preserved': {(k.name, k.frame) for k in baseline.bones}.issubset(
                  {(k.name, k.frame) for k in refined.bones})}
    if args.apply:
        from mmd_mcp import scene_controls as scene, file_operations as files
        from mmd_mcp.bone_controls import AxisValues
        from mmd_mcp.bone_state import list_bones
        from mmd_mcp.authoring_live import preview_motion
        from mmd_mcp.capture import capture_png
        from mmd_mcp.windows import select_window
        from mmd_mcp.ui_state import get_ui_state
        window = select_window(args.hwnd)
        actual = list_bones(args.hwnd)
        profile = read_profile(args.model)
        if [b['name'] for b in actual['bones']] != [b['name'] for b in profile['bones']]:
            raise ValueError('Select the Tda test model first; active bone signature differs.')
        model_index = get_ui_state(args.hwnd)['model_selector']['selected_index']
        scene.set_frame(0, args.hwnd)
        scene.select_model(0, None, args.hwnd)
        scene.set_camera(position=AxisValues(x=0, y=10.5, z=0), rotation_degrees=AxisValues(x=0, y=0, z=0),
                         distance=39, fov_degrees=32, hwnd=args.hwnd)
        scene.register_keyframe('camera', None, args.hwnd)
        for name in ['static', 'baseline', 'refined']:
            current = select_window(args.hwnd)
            if (current.pid, current.process_started) != (window.pid, window.process_started):
                raise RuntimeError('Demo process changed.')
            scene.select_model(model_index, None, args.hwnd)
            scene.set_frame(0, args.hwnd)
            result = files.load_file('motion', str(args.output/f'{name}.vmd'), args.hwnd)
            if result['status'] != 'completed':
                raise RuntimeError(result)
            scene.select_model(0, None, args.hwnd)
            if name != 'static':
                report[name+'_preview'] = preview_motion(str(args.output/(name+'-preview')),
                    0, 150, args.preview_step, True, args.hwnd)
                scene.set_frame(60, args.hwnd)
            time.sleep(.3)
            (args.output/f'{name}.png').write_bytes(capture_png(args.hwnd))
            result = files.save_project(str(args.output/f'{name}.pmm'), False, args.hwnd)
            if result['status'] != 'completed':
                raise RuntimeError(result)
            print(name+' complete', flush=True)
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(args.output, flush=True)


if __name__ == '__main__':
    main()
