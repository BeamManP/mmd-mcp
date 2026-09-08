"""Build two model-bound Tda jump/joy clips without reference-motion input."""
import argparse,importlib.util,json,struct
from pathlib import Path
from mmd_mcp.pose_authoring import read_profile,compile_with_profile,ArmPose,SemanticPose,TDA_SHA256
from mmd_mcp.motion_document import MotionDocument,save_document,vmd_bytes,encoded_name
SMOOTH=dict(x1=42,y1=0,x2=85,y2=127)
LINEAR=dict(x1=20,y1=20,x2=107,y2=107)
FAST_OUT=dict(x1=42,y1=85,x2=85,y2=127)
FAST_IN=dict(x1=42,y1=0,x2=85,y2=42)

def build(model_path,out,kind='joy',inertia=True):
    profile=read_profile(str(Path(model_path).resolve()))
    if profile['model_sha256']!=TDA_SHA256:raise ValueError('Exact Tda V4X 1.00 model required')
    if kind not in ['jump','joy']:raise ValueError('Unknown kind')
    if type(inertia) is not bool:raise ValueError('inertia must be a boolean')
    out=Path(out).resolve();out.mkdir(exist_ok=False)
    end=144 if kind=='joy' else 100
    keys={}
    def put(n,f,pos=(0.,0.,0.),rot=(0.,0.,0.),curve=SMOOTH):
        keys[n,f]={'name':n,'frame':f,'position':dict(zip('xyz',map(float,pos))),
            'rotation_degrees':dict(zip('xyz',map(float,rot))),
            'interpolation':{c:dict(curve) for c in ['x','y','z','rotation']}}
    def arm(lift=-37.5,bend=8.,forward=0.,gesture='relaxed',palm=None):
        return ArmPose(arm_lift=float(lift),elbow_bend=float(bend),arm_forward=float(forward),gesture=gesture,palm_facing=palm)
    def gathered(offset=0):
        # FK-solved right wrist (-1.824,15.713,-1.802) on this exact rig;
        # mirrored left chain is checked in native front/oblique renders.
        return arm(-38+offset,138,-66,'fist')
    rest=compile_with_profile(profile,SemanticPose(left_arm=arm(),right_arm=arm()),solve=False)['bones']
    names={b['name'] for b in profile['bones']}
    for k in rest:keys[k['name'],0]={**k,'frame':0}
    for n in ['全ての親','センター','グルーブ','腰','下半身','上半身','上半身2','首','頭','両目','左足ＩＫ','右足ＩＫ','左つま先ＩＫ','右つま先ＩＫ','右肩P','左肩P','右腕捩','左腕捩']:
        if n in names:put(n,0)
    # Translation apex and flight duration define an animation acceleration,
    # not Earth gravity: no physical meter scale is assumed for the model.
    h=2.6;takeoff=26;apex=36;contact=46
    for f,y,c in [(0,0.,SMOOTH),(8,0.,SMOOTH),(20,-1.5,SMOOTH),(26,0.,FAST_IN),
                  (46,0.,LINEAR),(51,-1.15,FAST_OUT),(61,-.035,SMOOTH),(70,-.12,SMOOTH),(82,0.,SMOOTH),(end,0.,SMOOTH)]:
        put('センター',f,pos=(0,y,0),curve=c)
    # One-frame air keys make the parabola exact at the render samples;
    # foot IK carries its toe child, whose local translation remains zero.
    for f in range(takeoff,contact+1):
        y=h*(1-((f-apex)/(apex-takeoff))**2)
        put('センター',f,pos=(0,y,0),curve=FAST_IN if f==takeoff else LINEAR)
        for side in ['右','左']:put(side+'足ＩＫ',f,pos=(0,y,0),curve=LINEAR)
    for side in ['右','左']:
        put(side+'足ＩＫ',end)
        put(side+'つま先ＩＫ',end)
    # Forward pitch is intentionally modest so planted legs remain reachable.
    for f,bow in [(0,0),(8,0),(20,14),(28,-5),(39,-3),(47,2),(53,11),(63,-2.5),(74,1),(84,0),(end,0)]:
        put('上半身',f,rot=(bow*.45,0,0))
        put('上半身2',f+(2 if inertia and f not in [0,end] else 0),rot=(bow*.55,0,0))
    for f,nod in [(0,0),(12,-3),(23,2),(31,-5),(42,-3),(50,0),(56,5),(65,-2),(77,0),(end,0)]:
        put('頭',f if inertia or f in [0,end] else max(0,f-3),rot=(nod,0,2 if kind=='joy' and 31<=f<=77 else 0))
    if kind=='joy':
        for f,nod,tilt in [(86,0,2),(99,4,5),(108,7,7),(121,-2,5),(132,1,5),(144,1,5)]:
            put('頭',f,rot=(nod,-3,tilt))
    poses=[]
    if kind=='joy':
        poses=[(0,arm(),arm()),(9,arm(),arm()),
            (20,gathered(),gathered(2)),
            (31,arm(82,28,8,'open','camera'),arm(65,38,14,'open','camera')),
            (43,arm(72,34,8,'open','camera'),arm(58,44,14,'open','camera')),
            (53,arm(57,46,10,'open','camera'),arm(44,56,16,'open','camera')),
            (63,arm(72,34,8,'open','camera'),arm(58,44,14,'open','camera')),
            (74,arm(68,37,8,'open','camera'),arm(55,47,14,'open','camera')),
            (84,arm(68,37,8,'open','camera'),arm(55,47,14,'open','camera')),
            (104,gathered(),gathered(2)),
            (114,gathered(3),gathered(5)),
            (126,gathered(),gathered(2)),
            (end,gathered(),gathered(2))]
    else:
        poses=[(0,arm(),arm()),(8,arm(),arm()),(20,arm(-27,18,24),arm(-27,18,24)),
            (31,arm(-8,24,-22),arm(-8,24,-22)),(43,arm(-14,20,-15),arm(-14,20,-15)),
            (53,arm(-25,28,-22),arm(-25,28,-22)),(64,arm(-32,8,8),arm(-32,8,8)),
            (76,arm(),arm()),(end,arm(),arm())]
    for f,right,left in poses:
        compiled=compile_with_profile(profile,SemanticPose(left_arm=left,right_arm=right))['bones']
        for k in compiled:
            n=k['name']
            if not n.startswith(('右','左')) or any(t in n for t in ['足','つま先']):continue
            lag=0
            if inertia and f not in [0,end]:
                lag=2 if 'ひじ' in n else 3 if any(t in n for t in ['手','指']) else 0
            keys[n,min(end,f+lag)]={**k,'frame':min(end,f+lag),'interpolation':{c:dict(SMOOTH) for c in ['x','y','z','rotation']}}
    morphs=[{'name':'AL未使用','frame':0,'weight':1.}]
    if kind=='joy':
        for n,fs in {'にっこり':[(0,0.),(16,.2),(25,.65),(35,.85),(61,.75),(84,.75),(97,.9),(126,.75),(end,.75)],
                     'あ':[(0,0.),(22,0.),(29,.3),(44,.22),(62,.15),(88,.12),(103,0.),(end,0.)],
                     'まばたき':[(0,0.),(17,0.),(20,.6),(24,0.),(93,0.),(97,1.),(101,0.),(end,0.)],
                     '笑い':[(0,0.),(26,0.),(32,.45),(40,.25),(54,.1),(85,.1),(104,.65),(114,.65),(128,.35),(end,.35)]}.items():
            morphs +=[{'name':n,'frame':f,'weight':v} for f,v in fs]
    doc=MotionDocument.model_validate({'model_name':profile['model_name'],'model_sha256':profile['model_sha256'],'bones':list(keys.values()),'morphs':morphs})
    save_document(doc,str(out/'motion.json'),'json')
    data=vmd_bytes(doc)
    assert data[-16:]==bytes(16)
    flags=struct.pack('<IIBI',1,0,1,4)
    for n in ['右足ＩＫ','右つま先ＩＫ','左足ＩＫ','左つま先ＩＫ']:flags+=encoded_name(n,20)+bytes([1])
    with (out/'motion.vmd').open('xb') as stream:stream.write(data[:-4]+flags)
    manifest={'kind':kind,'inertia':inertia,'model_sha256':profile['model_sha256'],'last_frame':end,'flight':{'takeoff':takeoff,'apex':apex,'contact':contact,'height':h,'acceleration_units_per_frame2':2*h/100},'scope':'Independent prototype; explicit foot targets, no mass/contact or physical secondary-motion solver. Fixed Tda model only. This new file has not yet been loaded into MMD.'}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    return out

import math
_spec=importlib.util.spec_from_file_location('inertia_wave_math',Path(__file__).with_name('wave_recipe.py'))
w=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)

def validate_records(records,manifest,profile):
    tracks=w.tracks_from_records(records);errors=[]
    if manifest['model_sha256']!=profile['model_sha256']:errors.append('model_mismatch')
    required={'センター','右足ＩＫ','左足ＩＫ','右つま先ＩＫ','左つま先ＩＫ'}
    if required-set(tracks):return {'passed':False,'errors':['missing_tracks:'+','.join(sorted(required-set(tracks)))]}
    def pos(n,f):return w.evaluate(tracks[n],f)[0]
    end=manifest['last_frame'];flight=manifest['flight'];start,apex,finish=[flight[k] for k in ['takeoff','apex','contact']]
    if max(r['frame'] for r in records)!=end:errors.append('clip_length')
    flags=[r for r in records if r['track']=='model_flags']
    initial={ik['name']:ik['enabled'] for flag in flags if flag['frame']==0 for ik in flag['ik']}
    for n in required-{'センター'}:
        if initial.get(n) is not True:errors.append('initial_ik_not_enabled:'+n)
        if any(ik['name']==n and not ik['enabled'] for flag in flags for ik in flag['ik']):errors.append('ik_disabled:'+n)
    for n,ks in tracks.items():
        if ks[0]['frame']!=0:errors.append('initial:'+n)
    ys=[pos('センター',f)['y'] for f in range(end+1)]
    velocity=[b-a for a,b in zip(ys,ys[1:])]
    acc=[b-a for a,b in zip(velocity,velocity[1:])]
    if max(abs(acc[f-1]+flight['acceleration_units_per_frame2']) for f in range(start+1,finish))>1e-5:errors.append('air_acceleration')
    if abs(ys[apex]-flight['height'])>1e-5:errors.append('apex_height')
    if abs(velocity[start]-velocity[start-1])>.1:errors.append('launch_velocity_discontinuity')
    if abs(velocity[finish]-velocity[finish-1])>.12:errors.append('contact_velocity_discontinuity')
    if not (-2.<min(ys[finish:finish+10])<-.5):errors.append('landing_absorption')
    rest={b['name']:b['rest_position'] for b in profile['bones']}
    reach=[]
    for side in ['右','左']:
        length=math.dist(rest[side+'足'],rest[side+'ひざ'])+math.dist(rest[side+'ひざ'],rest[side+'足首'])
        for f in range(end+1):
            p=pos(side+'足ＩＫ',f);toe=pos(side+'つま先ＩＫ',f)
            if any(abs(p[a])>1e-5 for a in 'xz'):errors.append('foot_slide:'+side+str(f))
            expected=ys[f] if start<=f<=finish else 0.
            if abs(p['y']-expected)>1e-5:errors.append('foot_support_or_air:'+side+str(f))
            if any(abs(toe[a])>1e-5 for a in 'xyz'):errors.append('toe_double_translation:'+side+str(f))
            hip=[rest[side+'足'][0],rest[side+'足'][1]+ys[f],rest[side+'足'][2]]
            ankle=[rest[side+'足ＩＫ'][i]+p[a] for i,a in enumerate('xyz')]
            ratio=math.dist(hip,ankle)/length;reach.append(ratio)
            if ratio>1.001:errors.append('unreachable:'+side+str(f))
    if manifest['kind']=='jump':
        for n,ks in tracks.items():
            a,q=w.evaluate(ks,0);b,r=w.evaluate(ks,end)
            if math.dist(list(a.values()),list(b.values()))>1e-5 or w.angular_distance(q,r)>.002:errors.append('rest_end:'+n)
    return {'passed':not errors,'errors':errors,'launch_velocity_before_after':[velocity[start-1],velocity[start]],'landing_velocity_before_after':[velocity[finish-1],velocity[finish]],'max_leg_reach_ratio':max(reach),'scope':'IK targets and unrotated pelvis chain geometry; rendered soles/physics require live QA.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',required=True,type=Path,help='Exact licensed Tda V4X Ver1.00 PMX path')
    parser.add_argument('--output',required=True,type=Path,help='New directory; existing paths are rejected')
    parser.add_argument('--kind',choices=['jump','joy'],default='joy')
    parser.add_argument('--no-additional-lag',action='store_true',help='Comparison only: omit added 2-3F chain offsets; other anticipation/settling remains')
    args=parser.parse_args()
    out=build(args.model,args.output,args.kind,not args.no_additional_lag)
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf8'))
    result=validate_records(w.read_records(out/'motion.vmd'),manifest,read_profile(str(args.model.resolve())))
    (out/'trajectory-qa.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    if not result['passed']:raise ValueError(result['errors'])
    print(json.dumps({'output':str(out),'last_frame':manifest['last_frame'],'trajectory_qa':result['passed'],'loaded_into_mmd':False}))


if __name__=='__main__':main()
