"""Build and inspect a model-bound right-hand wave without touching live MMD.

Uses mmd-mcp's existing pose/FK and VMD modules. Does not ingest reference clips.
Run --help from the Python environment in which mmd-mcp is installed.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path

from mmd_mcp.motion_document import MotionDocument, save_document
from mmd_mcp.pose_authoring import ArmPose, SemanticPose, compile_with_profile, read_profile
from mmd_mcp import pose_fk
from mmd_mcp.rotation import axis_angle, from_ui, to_ui
from mmd_mcp.vmd_reader import inspect

RECIPE_PATH = Path(__file__).resolve().parents[1] / 'assets' / 'recipes' / 'tda-right-wave.json'
SMOOTH = {'x1': 42, 'y1': 0, 'x2': 85, 'y2': 127}
LINEAR = {'x1': 20, 'y1': 20, 'x2': 107, 'y2': 107}
ARM_NAMES = ['右肩', '右腕', '右ひじ', '右手捩', '右手首']
STATIC_NAMES = ['全ての親', 'センター', 'グルーブ', '腰', '下半身',
                '上半身', '上半身2', '首', '頭', '左足ＩＫ', '右足ＩＫ',
                '左つま先ＩＫ', '右つま先ＩＫ', '右肩P', '左肩P', '右腕捩', '左腕捩']


def load_recipe():
    data = json.loads(RECIPE_PATH.read_text(encoding='utf-8'))
    if data['version'] != 1:
        raise ValueError('Unsupported wave recipe version.')
    return data


def check_request(profile, recipe, style, cycles, speed):
    if profile['model_sha256'] != recipe['model_sha256']:
        raise ValueError('This recipe requires the exact Tda V4X Ver1.00 model SHA-256.')
    if style not in recipe['styles'] or speed not in recipe['speeds']:
        raise ValueError('Unknown style or speed.')
    if type(cycles) is not int or cycles not in recipe['cycles']:
        raise ValueError('cycles must be an integer in the tested recipe domain: 1, 2, 3.')


def build(profile, style='quiet', cycles=2, speed='normal', recipe=None):
    recipe = recipe or load_recipe()
    check_request(profile, recipe, style, cycles, speed)
    settings = recipe['styles'][style]
    timing = recipe['speeds'][speed]
    chain = pose_fk.arm_chain(profile, '右')
    rig_names = {b['name'] for b in profile['bones']}
    rest = compile_with_profile(profile, SemanticPose(
        left_arm=ArmPose(arm_lift=-37.5, elbow_bend=8., gesture='relaxed'),
        right_arm=ArmPose(arm_lift=-37.5, elbow_bend=8., gesture='relaxed')), solve=False)['bones']
    rest = {k['name']: k for k in rest}
    for name in STATIC_NAMES:
        if name in rig_names:
            rest[name] = {'name': name, 'frame': 0, 'position': dict.fromkeys('xyz', 0.),
                          'rotation_degrees': dict.fromkeys('xyz', 0.)}

    def pose(u):
        mix = (u + 1.) / 2.
        arm = ArmPose(arm_lift=float(settings['arm_lift_a'] * (1-mix) + settings['arm_lift_b'] * mix),
                      elbow_bend=float(settings['elbow_a'] * (1-mix) + settings['elbow_b'] * mix),
                      shoulder_lift=float(settings['shoulder_lift']), gesture='open', palm_facing='camera')
        r = compile_with_profile(profile, SemanticPose(
            left_arm=ArmPose(arm_lift=-37.5, elbow_bend=8., gesture='relaxed'), right_arm=arm))
        keys = {k['name']: k for k in r['bones'] if k['name'].startswith('右') and k['name'] not in ['右足ＩＫ']}
        # In the unposed wrist frame, rotation about the rest palm normal leaves
        # its facing direction intact, while the fingertips sweep in that plane.
        wrist = axis_angle(chain['palm'], settings['wrist_swing_degrees'] * u)
        keys['右手首']['rotation_degrees'] = dict(zip('xyz', to_ui(wrist)))
        return keys

    poses = {u: pose(u) for u in (-1., 0., 1.)}
    settle_pose = dict(poses[0.])
    if settings['settle_arm'] == 'last_endpoint':
        for name in ARM_NAMES[:-1]:
            settle_pose[name] = poses[-1.][name]
    moving = sorted(poses[-1.])
    keys = {}
    def put(key, frame, curve=SMOOTH):
        value = {**key, 'frame': frame, 'interpolation': {c: dict(curve) for c in ('x','y','z','rotation')}}
        keys[(value['name'], frame)] = value
    for k in rest.values():
        put(k, 0)

    begin = timing['raise']
    wave_end = begin + cycles * timing['period']
    lag_end = wave_end + settings['wrist_lag']
    settled = lag_end + timing['settle']
    lower_begin = settled + timing['hold']
    lower_end = lower_begin + timing['lower']
    final = lower_end + timing['rest']
    # Small tested arrival offsets apply only while raising/lowering, not to
    # planted feet or to a blanket offset of the whole clip.
    arrivals = {'右肩': -4, '右腕': -3, '右ひじ': -2, '右手捩': -1, '右手首': 0}
    for name in moving:
        put(poses[-1.][name], begin + arrivals.get(name, 0))
        put(poses[-1.][name], begin)
    oscillating = ['右手首'] if style == 'quiet' else ['右腕', '右ひじ', '右手捩', '右手首']
    events = [{'frame': begin, 'pose': 'A'}]
    for i in range(1, cycles*2+1):
        frame = begin + i * (timing['period']//2)
        u = 1. if i % 2 else -1.
        events.append({'frame': frame, 'pose': 'B' if i % 2 else 'A'})
        for name in oscillating:
            delay = settings['wrist_lag'] if name == '右手首' else 0
            put(poses[u][name], frame + delay)
    for name in moving:
        # A hold at lag_end prevents interpolation from slowly drifting toward
        # the settled pose throughout the repeated phase on static arm tracks.
        put(poses[-1.][name], lag_end)
        put(settle_pose[name], settled)
        put(settle_pose[name], lower_begin)
        put(rest[name], lower_end + arrivals.get(name, 0))
        put(rest[name], lower_end)
    for k in rest.values():
        put(k, final)
    doc = MotionDocument.model_validate({'model_name': profile['model_name'],
        'model_sha256': profile['model_sha256'], 'bones': [keys[k] for k in sorted(keys)],
        'morphs': [{'name':'AL未使用','frame':0,'weight':1.}, {'name':'AL未使用','frame':final,'weight':1.}]})
    manifest = {'recipe_id': recipe['id'], 'recipe_sha256': hashlib.sha256(RECIPE_PATH.read_bytes()).hexdigest(),
        'style':style, 'cycles':cycles, 'speed':speed, 'fps':30, 'model_sha256':profile['model_sha256'],
        'events':events, 'phases':{'raise':[0,begin], 'wave':[begin,lag_end], 'settle':[lag_end,settled],
        'hold':[settled,lower_begin], 'lower':[lower_begin,lower_end], 'rest':[lower_end,final]},
        'last_frame':final, 'elapsed_seconds':final/30, 'sample_count_inclusive':final+1,
        'count_definition':recipe['count_definition'], 'minimum_tip_span':settings['minimum_tip_span'],
        'live_verified':False}
    return doc, manifest


def bezier_amount(t, curve):
    if t <= 0: return 0.
    if t >= 1: return 1.
    x1,y1,x2,y2 = [curve[k]/127. for k in ('x1','y1','x2','y2')]
    lo,hi=0.,1.
    for _ in range(35):
        u=(lo+hi)/2.;x=3*(1-u)**2*u*x1+3*(1-u)*u*u*x2+u**3
        if x<t:lo=u
        else:hi=u
    u=(lo+hi)/2.
    return 3*(1-u)**2*u*y1+3*(1-u)*u*u*y2+u**3


def normalize(q):
    length=math.sqrt(sum(v*v for v in q))
    if not length or not math.isfinite(length):raise ValueError('Invalid quaternion.')
    return tuple(v/length for v in q)


def slerp(a,b,t):
    a,b=normalize(a),normalize(b)
    dot=sum(x*y for x,y in zip(a,b))
    if dot<0:b=tuple(-v for v in b);dot=-dot
    dot=min(1.,dot)
    if dot>.9995:return normalize(tuple(x*(1-t)+y*t for x,y in zip(a,b)))
    angle=math.acos(dot);denom=math.sin(angle)
    return tuple((math.sin((1-t)*angle)*x+math.sin(t*angle)*y)/denom for x,y in zip(a,b))


def angular_distance(a,b):
    dot=abs(sum(x*y for x,y in zip(normalize(a),normalize(b))))
    return math.degrees(2*math.acos(min(1.,dot)))


def read_records(path):
    rows=[];offset=0
    while True:
        result=inspect(str(Path(path).resolve()),offset=offset,limit=1000)
        rows.extend(result['records'])
        if result['next_offset'] is None:break
        offset=result['next_offset']
    return rows


def tracks_from_records(records):
    tracks={}
    for k in records:
        if k['track']=='bones':tracks.setdefault(k['name'],[]).append(k)
    for keys in tracks.values():keys.sort(key=lambda k:k['frame'])
    return tracks


def evaluate(keys, frame):
    index=bisect.bisect_right([k['frame'] for k in keys],frame)
    if index==0:k=keys[0];return k['position'],k['quaternion_xyzw']
    if index==len(keys):k=keys[-1];return k['position'],k['quaternion_xyzw']
    a,b=keys[index-1:index+1]
    t=(frame-a['frame'])/(b['frame']-a['frame'])
    pos={axis:a['position'][axis]+(b['position'][axis]-a['position'][axis])*bezier_amount(t,b['interpolation'][axis]) for axis in 'xyz'}
    return pos,slerp(a['quaternion_xyzw'],b['quaternion_xyzw'],bezier_amount(t,b['interpolation']['rotation']))


def validate_records(profile, records, manifest):
    """Independent trajectory gates on emitted VMD, not on requested event count alone."""
    recipe=load_recipe()
    check_request(profile,recipe,manifest['style'],manifest['cycles'],manifest['speed'])
    if manifest['model_sha256'] != profile['model_sha256']:raise ValueError('Manifest/model mismatch.')
    tracks=tracks_from_records(records)
    issues=[]
    foot_ik_names={'左足ＩＫ','右足ＩＫ','左つま先ＩＫ','右つま先ＩＫ'}
    flags=[k for k in records if k['track']=='model_flags']
    for flag in flags:
        for ik in flag['ik']:
            if ik['name'] in foot_ik_names and not ik['enabled']:
                issues.append('foot_ik_disabled:'+ik['name'])
    final=manifest['last_frame']
    if max(r['frame'] for r in records)!=final:issues.append('last_frame_mismatch')
    for name,keys in tracks.items():
        if keys[0]['frame'] != 0:issues.append('missing_initial_key:'+name)
        if len({k['frame'] for k in keys}) != len(keys):issues.append('duplicate_frame:'+name)
        p0,q0=evaluate(keys,0);p1,q1=evaluate(keys,final)
        if max(abs(p0[c]-p1[c]) for c in 'xyz')>1e-5 or angular_distance(q0,q1)>1e-3:
            issues.append('end_pose_mismatch:'+name)
        active = name in ARM_NAMES or (name.startswith('右') and any(f in name for f in ['親指','人指','中指','薬指','小指']))
        if not active and any(max(abs(k['position'][c]-p0[c]) for c in 'xyz')>1e-6 or angular_distance(k['quaternion_xyzw'],q0)>1e-3 for k in keys):
            issues.append('unrelated_track_moves:'+name)
    required=['センター','上半身','上半身2','頭','左足ＩＫ','右足ＩＫ']+ARM_NAMES
    missing=set(required)-set(tracks)
    issues.extend('missing_track:'+name for name in sorted(missing))
    for name in STATIC_NAMES:
        for k in tracks.get(name,[]):
            if max(abs(v) for v in k['position'].values())>1e-6 or angular_distance(k['quaternion_xyzw'],(0,0,0,1))>1e-3:
                issues.append('static_support_or_torso_changed:'+name);break
    if missing:return {'passed':False,'issues':issues,'limits':['Cannot evaluate a missing arm/torso/foot track.']}
    chain=pose_fk.arm_chain(profile,'右')
    start,end=manifest['phases']['wave']
    samples=[]
    max_joint_step=0.;max_tip_step=0.;min_palm_dot=1.;prev=None
    for frame in range(final+1):
        quats={n:evaluate(tracks[n],frame)[1] for n in ARM_NAMES}
        r=pose_fk.evaluate_arm(chain,'右',{n:to_ui(q) for n,q in quats.items()})
        point=r['fingertip']
        if prev:
            max_joint_step=max(max_joint_step,max(angular_distance(prev['quats'][n],quats[n]) for n in ARM_NAMES))
            max_tip_step=max(max_tip_step,math.dist(prev['point'],point))
        prev={'quats':quats,'point':point}
        if start<=frame<=end:
            samples.append({'frame':frame,'tip':point,'wrist':r['wrist'],'palm_camera_dot':-r['palm_normal'][2]})
            min_palm_dot=min(min_palm_dot,-r['palm_normal'][2])
    a=samples[0]['tip']
    first_b=min(samples,key=lambda s:abs(s['frame']-manifest['events'][1]['frame']))['tip']
    axis=tuple(b-x for b,x in zip(first_b,a));span=math.sqrt(sum(x*x for x in axis))
    if span<manifest['minimum_tip_span']:issues.append('insufficient_visible_tip_span')
    seen_b=False;count=0;visits=[]
    if span>1e-9:
        for s in samples:
            amount=sum((x-y)*z for x,y,z in zip(s['tip'],a,axis))/(span*span)
            s['projected_phase']=amount
            if not seen_b and amount>=.85:
                seen_b=True;visits.append({'frame':s['frame'],'endpoint':'B'})
            elif seen_b and amount<=.15:
                seen_b=False;count+=1;visits.append({'frame':s['frame'],'endpoint':'A'})
    if count!=manifest['cycles'] or seen_b:issues.append('visible_round_trip_count_mismatch')
    if min_palm_dot<.85:issues.append('palm_turns_away_during_wave')
    if max_joint_step>22.:issues.append('joint_step_over_22_degrees')
    if max_tip_step>1.5:issues.append('tip_step_over_1_5_units')
    return {'passed':not issues,'issues':issues,'observed_round_trips':count,'endpoint_visits':visits,
        'tip_span':round(span,5),'minimum_palm_camera_dot':round(min_palm_dot,5),
        'max_joint_step_degrees':round(max_joint_step,5),'max_tip_step_units':round(max_tip_step,5),
        'samples':samples,
        'foot_ik_flags_present':bool(flags),
        'hand_probe':'Rest middle-finger-2 point transformed by arm/wrist FK; individual finger articulation is not evaluated.',
        'limits':['FK covers this static-torso arm construction, not arbitrary imported motion, full rig grant/IK or physics.',
                  'Static support keys are checked, not sole-to-floor collision or contact forces.',
                  'These numerical gates require real MMD visual validation before adoption.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--model',required=True);b.add_argument('--output',required=True)
    b.add_argument('--style',choices=['quiet','broad'],default='quiet')
    b.add_argument('--cycles',type=int,choices=[1,2,3],default=2)
    b.add_argument('--speed',choices=['brisk','normal','slow'],default='normal')
    v=sub.add_parser('validate');v.add_argument('--model',required=True);v.add_argument('--vmd',required=True)
    v.add_argument('--manifest',required=True);v.add_argument('--report',required=True)
    args=parser.parse_args();profile=read_profile(str(Path(args.model).resolve()))
    if args.command=='build':
        doc,manifest=build(profile,args.style,args.cycles,args.speed)
        out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
        save_document(doc,str(out/'motion.json'),'json');save_document(doc,str(out/'motion.vmd'),'vmd')
        (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        result=validate_records(profile,read_records(out/'motion.vmd'),manifest)
        (out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'directory':str(out),'last_frame':manifest['last_frame'],'passed':result['passed'],'issues':result['issues']}))
        if not result['passed']:raise SystemExit(2)
    else:
        manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        result=validate_records(profile,read_records(args.vmd),manifest)
        with Path(args.report).open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
        print(json.dumps({k:v for k,v in result.items() if k not in ['samples']}))
        if not result['passed']:raise SystemExit(2)


if __name__=='__main__':
    main()
