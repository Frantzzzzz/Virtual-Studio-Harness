import json,math,sys,hashlib
from paths import OUT,HARNESS
sys.path.insert(0,str(HARNESS))
from camera_agent.motion.expert_route import build
from camera_agent.motion import sample_motion
from camera_agent.tool.camera_tool_result import normalize_camera_tool_result
from camera_agent.harness.backends.sequence import compose
P=OUT/'project';plan=json.loads((P/'camera_plan.json').read_text());studio=json.loads((P/'shared_studio.json').read_text());actions=json.loads((P/'action_plan.json').read_text());native=json.loads((OUT/'native_motion_samples.json').read_text());details=json.loads((OUT/'camera_catalog.json').read_text());manifest=json.loads((OUT/'actor_clip_manifest.json').read_text())
origin=studio['origin_blender'];views={v['id']:v for v in studio['camera_views']};fps=24;T=actions['duration_s'];N=round(T*fps)
def bridge(p):return [origin[0]+p[0],origin[1]-p[2],origin[2]+p[1]]
def actor_at(t,ident):
    if t>=T:return list(studio['anchors'][actions['actors'][ident]['root_keys'][-1]['node']]['position'])
    p=max(0,min(N-1,t*fps));i=int(p);j=min(i+1,N-1);f=p-i
    a,b=native[i]['actors'][ident]['position'],native[j]['actors'][ident]['position'];return [x+(y-x)*f for x,y in zip(a,b)]
candidates=[];intent={'shots':[]};cursor=0;camera_samples=[]
for shot in plan['shots']:
    assert abs(shot['start_s']-cursor)<1e-7 and shot['end_s']>cursor
    assert abs(shot['start_s']*fps-round(shot['start_s']*fps))<1e-7 and abs(shot['end_s']*fps-round(shot['end_s']*fps))<1e-7
    cursor=shot['end_s'];sd=shot['end_s']-shot['start_s'];count=round(sd*fps);view=views[shot['station_id']]
    fov=view['fov_y_deg'] if shot['fov_y_deg'] is None else shot['fov_y_deg'];assert 15<=fov<=110
    lens=(36/(16/9))/(2*math.tan(math.radians(fov)/2));times=[i/fps for i in range(count+1)]
    positions=[];aim=[]
    for local in times:
        pos=list(view['position']);target=list(view['target'])
        if shot['mode']=='track_subject':
            assert shot['follow_actor']=='CHAR-0002' and shot['state']=='carry'
            ref=details['calibration_states']['carry']['actors']['CHAR-0002']['position'];now=actor_at(shot['start_s']+local,shot['follow_actor']);delta=[a-b for a,b in zip(now,ref)]
            pos=[a+b for a,b in zip(pos,delta)];target=[a+b for a,b in zip(target,delta)]
        elif shot['mode']=='push_in':
            assert shot['follow_actor'] is None and 0<shot['push_distance']<=.8
            delta=[a-b for a,b in zip(target,pos)];length=math.sqrt(sum(v*v for v in delta));pos=[a+b/length*shot['push_distance']*local/sd for a,b in zip(pos,delta)]
        else:assert shot['mode']=='static' and shot['follow_actor'] is None and shot['push_distance']==0
        positions.append(bridge(pos));aim.append(bridge(target))
    parameters={'position':{'times_s':times,'values_m':positions},'aim':{'mode':'world','times_s':times,'points_m':aim},'lens':{'times_s':[0],'values_mm':[lens]}}
    motion=build({'shot':{'duration_s':sd},'parameters':parameters})
    trajectory=sample_motion(motion,fps,shot['id'],{'projection_type':'PERSP','sensor_fit':'HORIZONTAL','sensor_width_mm':36,'clip_start':.05,'clip_end':500},start_frame=1)
    result=normalize_camera_tool_result({'schema':'camera_tool_result.v0.2','run_id':'forest_shared_stage_v2','status':'success','scene_id':'forest_capsules',
        'trajectory':trajectory,'provenance':[{'shot_id':shot['id'],'tool_call_id':'photography_director','frame_range':[1,count+1],'effective_params':parameters}]})
    candidates.append({'tool_result':result});intent['shots'].append({'id':shot['id'],'duration_s':sd,'transition':'cut'})
assert abs(cursor-T)<1e-7
joined,boundaries=compose(candidates,intent)
for block,spec in zip(joined['trajectory']['shots'],plan['shots']):
    for frame in block['frames']:camera_samples.append({'frame':frame['frame'],'shot':spec['id'],'camera_name':block['camera_name'],**frame,'required_actors':spec['required_actors'],'require_box':spec['require_box']})
assert len(camera_samples)==N and [r['frame'] for r in camera_samples]==list(range(1,N+1))
tb,tr=actions['events'][1]['t'],actions['events'][2]['t']
assert any(s['start_s']<tb and s['end_s']>tr+.2 and {'CHAR-0001','CHAR-0002'}<=set(s['required_actors']) and s['require_box'] for s in plan['shots']), 'Handover must remain in one shot'
assert set(plan['shots'][0]['required_actors'])==set(actions['actors'])
def dump(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
dump('camera_tool_result.json',joined);dump('camera_samples.json',camera_samples)
dump('camera_compile_checks.json',{'status':'compiled_not_visually_approved','frames':N,'shots':len(plan['shots']),'duration_s':T,'boundaries':boundaries,
 'binding':manifest,'camera_plan_sha256':hashlib.sha256((P/'camera_plan.json').read_bytes()).hexdigest(),'engine':'existing expert_route, sample_motion, sequence.compose'})
print('CAMERA_COMPILED',len(plan['shots']),N)
