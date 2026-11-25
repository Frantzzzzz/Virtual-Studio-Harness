"""Expand an upstream-authored recipe; never select timing, routes or posture."""
import json,math,sys,copy,hashlib
from paths import OUT,HARNESS,WORLDOS
sys.path[:0]=[str(HARNESS),str(WORLDOS)]
from modules.whitebox import sample,hand_anchor
from camera_agent.motion.standin_samples import compile_standin_samples
P=OUT/'project';plan=json.loads((P/'action_plan.json').read_text());studio=json.loads((P/'shared_studio.json').read_text())
nav=json.loads((OUT/'navigation_details.json').read_text());fps=24;T=plan['duration_s'];N=round(T*fps)
def check_time(t):assert type(t) in (int,float) and 0<=t<=T and abs(t*fps-round(t*fps))<1e-5,t
check_time(T);assert N>1
routes={frozenset((r['from'],r['to'])):r for r in nav['routes']};anchors=studio['anchors'];origin=studio['origin_blender']
def bridge(p):return [origin[0]+p[0],origin[1]-p[2],origin[2]+p[1]]
def interpolate_path(path,fraction):
    lengths=[math.dist(a,b) for a,b in zip(path,path[1:])];remaining=sum(lengths)*fraction
    for a,b,length in zip(path,path[1:],lengths):
        if remaining<=length+1e-9:
            alpha=max(0,min(1,remaining/length)) if length else 0
            return [x+(y-x)*alpha for x,y in zip(a,b)]
        remaining-=length
    return list(path[-1])
def root_at(actor,t):
    keys=actor['root_keys']
    i=next((i for i in range(len(keys)-1) if keys[i]['t']<=t<=keys[i+1]['t']),len(keys)-2);a,b=keys[i:i+2]
    if a['node']==b['node']:return list(anchors[a['node']]['position'])
    route=routes[frozenset((a['node'],b['node']))];path=route['path'] if route['from']==a['node'] else list(reversed(route['path']))
    return interpolate_path(path,max(0,min(1,(t-a['t'])/(b['t']-a['t']))))
actors={};reach_warnings=[]
for ident,actor in plan['actors'].items():
    assert ident in studio['actor_sizes']
    for kind in ['root_keys','pose_keys']:
        keys=actor[kind];assert keys[0]['t']==0 and keys[-1]['t']==T,(ident,kind)
        assert all(a['t']<b['t'] for a,b in zip(keys,keys[1:])),(ident,kind)
        for key in keys:check_time(key['t'])
    for a,b in zip(actor['root_keys'],actor['root_keys'][1:]):
        assert a['node'] in anchors and b['node'] in anchors
        assert a['node']==b['node'] or frozenset((a['node'],b['node'])) in routes,('Unmeasured route',ident,a,b)
    controls=[]
    for key in actor['pose_keys']:
        template=studio['interaction']['posture_templates'][key['pose']];pos=root_at(actor,key['t']);yaw=math.radians(key['yaw_deg'])
        if 'grip_world_anchor' in template:
            delta=[x-y for x,y in zip(studio['interaction'][template['grip_world_anchor']],pos)];c,s=math.cos(yaw),math.sin(yaw)
            grip=[c*delta[0]-s*delta[2],delta[1],s*delta[0]+c*delta[2]]
        else:grip=template['grip_local']
        bend=key.get('bend_rad') if key.get('bend_rad') is not None else template['bend']
        assert 0<=bend<=.8
        controls.append({'t':key['t'],'position':pos,'yaw':yaw,'pose':'stand','bend':bend,'right_hand':grip})
    dense=[]
    for i in range(N+1):
        t=i/fps;k=sample(controls,t);k['t']=t;k['position']=root_at(actor,t);dense.append(k)
    actors[ident]={'size_m':studio['actor_sizes'][ident],'keyframes':dense}
events=sorted(plan['events'],key=lambda e:e['t']);assert len(events)==4
assert [(e['kind'],e['actor']) for e in events]==[('hold','CHAR-0001'),('hold','CHAR-0002'),('release','CHAR-0001'),('release','CHAR-0002')]
assert all(a['t']<b['t'] for a,b in zip(events,events[1:]));assert T-events[-1]['t']>=.5
for event in events:check_time(event['t']);assert event['t']<T
owners=[];ownership=[];event_receipts=[];by_frame={round(e['t']*fps):e for e in events}
for i in range(N):
    if i in by_frame:
        e=by_frame[i];before=list(owners)
        if e['kind']=='hold':assert e['actor'] not in owners;owners.append(e['actor'])
        else:assert e['actor'] in owners;owners.remove(e['actor'])
        event_receipts.append(dict(e,before=before,after=list(owners),frame=i))
    ownership.append({'frame':i,'time':i/fps,'owners':{'box':list(owners)}})
free={'box':[{'t':0,'position':studio['interaction']['pickup_box']},
             {'t':events[0]['t'],'position':studio['interaction']['pickup_box']},
             {'t':events[-1]['t'],'position':studio['interaction']['drop_box']},
             {'t':T,'position':studio['interaction']['drop_box']}]}
sampled=compile_standin_samples(actors,ownership,free,sample=sample,hand_anchor=hand_anchor,point_transform=bridge,
    yaw_transform=lambda yaw:yaw-math.pi,max_shared_distance=.03,max_prop_step=.2)
rows,stats=sampled['samples'],sampled['diagnostics']
native_rows=[];max_reach_error=0;reach_worst=None
for i,row in enumerate(rows):
    native={};render={}
    for ident,actor in actors.items():
        key=actor['keyframes'][i];actual=hand_anchor(actor,key,'right_hand')[0]
        c,s=math.cos(key['yaw']),math.sin(key['yaw']);local=key['right_hand'];wanted=[key['position'][0]+c*local[0]+s*local[2],key['position'][1]+local[1],key['position'][2]-s*local[0]+c*local[2]]
        reach_error=math.dist(actual,wanted)
        if reach_error>max_reach_error:
            max_reach_error=reach_error;reach_worst={'actor':ident,'time_s':i/fps,'error':reach_error,'wanted':wanted,'actual':actual,'key':key,'owners':ownership[i]['owners']['box']}
        native[ident]={'position':key['position'],'yaw':key['yaw'],'grip':actual}
        render[ident]={'position':row['actors'][ident]['position'],'yaw':row['actors'][ident]['yaw'],'grip':row['actors'][ident]['anchor']}
    row['actors']=render;row['time_s']=row.pop('time');row['props']['box']['size_m']=studio['interaction']['box_size_m']
    native_rows.append({'frame':i+1,'time_s':i/fps,'actors':native,'owners':ownership[i]['owners']['box']})
(OUT/'reach_diagnostics.json').write_text(json.dumps(reach_worst,indent=2)+'\n')
assert max_reach_error<.01,('Interaction anchor exceeds arm proxy reach',max_reach_error,reach_worst['actor'],reach_worst['time_s'])
min_gap=min(math.hypot(a['position'][0]-b['position'][0],a['position'][1]-b['position'][1])-.44
    for row in rows for i,a in enumerate(row['actors'].values()) for b in list(row['actors'].values())[i+1:])
assert min_gap>=.2,('Dynamic actor proxy clearance',min_gap)
for e in events:
    i=round(e['t']*fps)
    jump=math.dist(rows[i-1]['props']['box']['position'],rows[i]['props']['box']['position'])
    assert jump<.04,('Ownership switch jumps',e,jump)
for a,b in zip(rows[-12:],rows[-11:]):assert math.dist(a['props']['box']['position'],b['props']['box']['position'])<1e-5
dump=lambda n,d:(OUT/n).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
dump('motion_samples.json',rows);dump('native_motion_samples.json',native_rows);dump('ownership_events.json',event_receipts)
key_times=sorted(set([0,(N-1)/fps]+[k['t'] for a in plan['actors'].values() for k in a['root_keys']]+[e['t'] for e in events]))
context={'duration_s':T,'fps':fps,'frame_count':N,'events':event_receipts,'beats':plan['beats'],'actor_root_keys':{id:a['root_keys'] for id,a in plan['actors'].items()},
         'pose_samples':[native_rows[min(N-1,round(t*fps))] for t in key_times],
         'binding':json.loads((P/'binding.json').read_text()),'role':'Upstream-authored motion expanded without changing timing or routes'}
(P/'motion_context.json').write_text(json.dumps(context,ensure_ascii=False,indent=2)+'\n')
dump('motion_compile_checks.json',{'status':'pass','frames':N,'duration_s':T,'sampling':stats,'maximum_proxy_reach_error':max_reach_error,
    'minimum_actor_proxy_gap':min_gap,'route_scope':'Only catalogue paths selected by the action director','source':'WorldOS sample/hand_anchor plus existing standin_samples; explicit four-event holding state machine, not CozyClay body simulation'})
dump('motion_binding.json',dict(context['binding'],action_plan_sha256=hashlib.sha256((P/'action_plan.json').read_bytes()).hexdigest(),
    motion_samples_sha256=hashlib.sha256((OUT/'motion_samples.json').read_bytes()).hexdigest()))
print('ACTIONS_COMPILED',T,N,min_gap,max_reach_error)
