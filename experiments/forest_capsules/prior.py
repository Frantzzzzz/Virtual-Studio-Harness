"""Bounded local studio facts, reusing actual camera-harness geometry queries."""
import sys,json,math,hashlib,time,copy
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from paths import OUT,HARNESS,WORLDOS,INDEX,CONFIG
sys.path[:0]=[str(HARNESS),str(WORLDOS)]
import bpy
from mathutils import Vector
from camera_agent.planning.scene_index import SceneIndex
from camera_agent.blender.trajectory_verifier import _collision_meshes,_evaluate_camera_containment,_verify_camera_segment
from camera_agent.blender.observation_geometry import assembly_visibility
from camera_agent.blender.view_search import search_views
from modules.whitebox import sample,prop_state

def dump(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
baseline=json.loads(CONFIG['baseline_episode'].read_text());origin=CONFIG['origin_blender']
source=CONFIG['source_blend'];source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
assert source_hash==CONFIG['source_sha256'], 'Source scene differs from configured version'
index_raw=json.loads(INDEX.read_text());index=SceneIndex(index_raw)
dump('harness_index_queries.json',{'terrain':index.search('Terrain'),'trees':index.search('Trees',limit=6)})
bpy.ops.wm.open_mainfile(filepath=str(CONFIG['calibration_blend']),load_ui=False,use_scripts=False)
s=bpy.context.scene;s.frame_set(1)
from capsules import replace_previous_people
replace_previous_people();bpy.context.view_layer.update()
# Restore every original cell hidden for the previous video; survey uses full source visibility.
for obj in index_raw['objects']:
    if obj['name'] in bpy.data.objects:bpy.data.objects[obj['name']].hide_render=bool(obj.get('hidden_render',False))
# Match the kitchen's declared proxy representation throughout survey and execution.
for obj in s.objects:
    if any(x in obj.name for x in ('_left_hand_','_right_hand_')):obj.hide_render=True;obj.hide_viewport=True
def bridge(p):return [origin[0]+p[0],origin[1]-p[2],origin[2]+p[1]]
def inverse(p):return [p[0]-origin[0],p[2]-origin[2],-(p[1]-origin[1])]
def bounds(obj):
    pts=[obj.matrix_world@Vector(v) for v in obj.bound_box]
    return [min(p[i] for p in pts) for i in range(3)],[max(p[i] for p in pts) for i in range(3)]
half=CONFIG['roi_half_extent']
roi=([origin[0]-half[0],origin[1]-half[1],origin[2]-.5],[origin[i]+half[i] for i in range(3)])
local=[]
for obj in s.objects:
    if obj.type!='MESH' or obj.name not in index.objects and 'object:'+obj.name not in index.objects:continue
    lo,hi=bounds(obj)
    if all(hi[i]>=roi[0][i] and lo[i]<=roi[1][i] for i in range(3)):local.append(obj)
deps=bpy.context.evaluated_depsgraph_get();records=_collision_meshes(deps,local)
assert any(r['name']=='Terrain' for r in records)
terrain=next(r['tree'] for r in records if r['name']=='Terrain')
forest=[r for r in records if r['name'].startswith(('Trees_cell_','RocksAndWood_cell_'))]
tables=[o for o in s.objects if o.name.startswith('PREVIS_STAGE_')]
table_records=_collision_meshes(deps,tables)
nav_obstacles=forest+table_records
def ground(x,z):
    wx,wy=origin[0]+x,origin[1]-z
    hit=terrain.ray_cast(Vector((wx,wy,30)),Vector((0,0,-1)),80)
    if hit[0] is None:raise ValueError('No measured terrain at requested anchor')
    return [x,hit[0].z-origin[2],z],float(abs(hit[1].z))
def clearance_at(point,recs,radius):
    p=Vector(point);minimum=float('inf');blockers=[]
    for record in recs:
        distance=record['tree'].find_nearest(p)[3];minimum=min(minimum,distance)
        if distance<radius or all(record['min'][i]<=p[i]<=record['max'][i] for i in range(3)):
            test=_evaluate_camera_containment(point,record,clearance=radius)
            if test['inside'] is not False:blockers.append({'object':record['name'],'reason':test['reason']})
    return dict(clear=not blockers,surface_distance=minimum,blockers=blockers,radius=radius,clearance_enforcement='required')
body_radius=.27;body_h=1.75;centres=[.25+(body_h-.5)*j/7 for j in range(8)]
def stand_check(pos):
    world=bridge(pos);checks=[clearance_at([world[0],world[1],world[2]+h],nav_obstacles,body_radius+.15) for h in centres]
    return {'clear':all(c['clear'] for c in checks),'minimum_proxy_surface_gap':min(c['surface_distance'] for c in checks)-body_radius}
anchor_xz=CONFIG['anchors_xz']
anchors={}
for name,(x,z) in anchor_xz.items():
    pos,normal=ground(x,z);check=stand_check(pos)
    anchors[name]={'position':pos,'terrain_normal_y':normal,'body_proxy':check}
dump('anchor_preflight.json',anchors)
assert all(a['body_proxy']['clear'] for a in anchors.values()),'Requested named anchors not all clear; see anchor_preflight.json'
routes=[];rejected=[]
for ai,(a,first) in enumerate(anchors.items()):
    for b,last in list(anchors.items())[ai+1:]:
        pa,pb=first['position'],last['position'];n=max(1,math.ceil(math.hypot(pb[0]-pa[0],pb[2]-pa[2])/.25))
        path=[ground(pa[0]+(pb[0]-pa[0])*i/n,pa[2]+(pb[2]-pa[2])*i/n)[0] for i in range(n+1)]
        reason=None
        for start,end in zip(path,path[1:]):
            for h in centres:
                aa=bridge(start);bb=bridge(end);aa[2]+=h;bb[2]+=h
                check=_verify_camera_segment(aa,bb,nav_obstacles,clearance=body_radius+.15)
                if not check['valid']:reason=check;break
            if reason:break
        if reason:rejected.append({'from':a,'to':b,'reason':reason})
        else:routes.append({'id':a+'__'+b,'from':a,'to':b,'path':path,'length':sum(math.dist(x,y) for x,y in zip(path,path[1:])),
                            'scope':'Measured ground polyline; swept sampled spheres with 0.15 clearance, excludes grass and leaning/arm volumes'})
    print('ROUTES',a,len(routes),flush=True)
grid=[]
for ix in range(-8,9):
    for iz in range(-6,7):
        p,norm=ground(ix*.5,iz*.5);c=stand_check(p);grid.append({'position':p,'normal':norm,**c})
props=baseline['groups'][0]['props'][0]
pickup=list(props['keyframes'][0]['position']);drop=list(baseline['groups'][2]['props'][0]['keyframes'][-1]['position'])
shared=[0,1.05,0]
interaction={'pickup_box':pickup,'shared_box':shared,'drop_box':drop,
    'tables':baseline['scenes']['SCN-0001']['objects'],'box_size_m':props['size_m'],
    'posture_templates':{'rest':{'bend':0,'grip_local':[0,1.02,.08]},'carry':{'bend':0,'grip_local':[0,1.02,.35]},
                         'pickup_contact':{'bend':.35,'grip_world_anchor':'pickup_box'},
                         'share_contact':{'bend':0,'grip_world_anchor':'shared_box'},
                         'drop_contact':{'bend':.38,'grip_world_anchor':'drop_box'}},
    'scope':'Invisible central interaction anchor, no anatomical grasp; upper director chooses posture and timing; new plans revalidated'}
dump('navigation_details.json',{'anchors':anchors,'routes':routes,'rejected_routes':rejected,'grid':grid})
dump('interaction_catalog.json',interaction)
all_camera_records=records+table_records
camera=s.camera;camera.animation_data_clear();camera.data.animation_data_clear()
camera.data.clip_start=.05;camera.data.clip_end=500
s.render.resolution_x=640;s.render.resolution_y=360;s.render.resolution_percentage=100
s.render.engine='BLENDER_EEVEE';s.eevee.taa_render_samples=8
def camera_clear(point):return clearance_at(point,all_camera_records,.15)
bad=bridge([3.98,2.05,.5]);regression={'position':bad,'harness_geometry':camera_clear(bad)}
dump('previous_bad_camera_regression.json',regression)
# Old animation is used only as a declared calibration pose set, not as new timing instructions.
states=[('establish',1,['CHAR-0001','CHAR-0002','CHAR-0003'],False),('pickup',55,['CHAR-0001'],True),
        ('handover',124,['CHAR-0001','CHAR-0002'],True),('carry',163,['CHAR-0002'],True),('drop',216,['CHAR-0002'],True)]
views=[];search_receipts={};calibrations={}
for state,frame,ids,box_needed in states:
    s.frame_set(frame);deps=bpy.context.evaluated_depsgraph_get()
    names=[id+suffix for id in ids for suffix in (['_body','_head'] if state=='establish' else ['_head'])]
    if box_needed:names.append('PREVIS_PROP_PROP-0001')
    objects=[bpy.data.objects[name] for name in names]
    target_records=_collision_meshes(deps,objects)
    dynamic=[o for o in s.objects if o.type=='MESH' and o.name.startswith(('CHAR-','PREVIS_PROP_'))]
    all_camera_records=records+table_records+_collision_meshes(deps,dynamic)
    meshes=[(r['name'],r['tree'],r['closed']) for r in target_records]
    lens=18 if state=='establish' else 35
    request={'lens_mm':lens,'projected_height':.32 if state=='establish' else .65,
        'azimuths_deg':[-150,-90,-30,30,90,150],'elevations_deg':[10,25],
        'max_views':3,'require_full_frame':True,'position_bounds':{'min':roi[0],'max':roi[1]}}
    selected,receipt=search_views(s,camera,objects,meshes,camera_clear,request)
    selected=[v for v in selected if all(value is not None and value>=.5 for value in v['visibility']['visible_ratio'].values())]
    search_receipts[state]=receipt
    calibrations[state]={'source_frame':frame,'scope':'Previous candidate used as a calibration posture only, not the new timeline',
        'actors':{id:{'position':inverse(bpy.data.objects['PREVIS_'+id].matrix_world.translation),
                      'head':inverse(bpy.data.objects[id+'_head'].matrix_world.translation)} for id in ids}}
    for i,v in enumerate(selected):
        ident=f'{state}_view_{i+1}';camera.location=v['xyz'];camera.rotation_mode='QUATERNION';camera.rotation_quaternion=(Vector(v['look_at'])-camera.location).to_track_quat('-Z','Y');bpy.context.view_layer.update()
        # Reuse actual foreground, trim only distant background for diagnostic thumbnails.
        hidden={o.name:o.hide_render for o in local}
        for o in s.objects:
            if o.name in index.objects or 'object:'+o.name in index.objects:
                lo,hi=bounds(o)
                if o.name.startswith(('Trees_cell_','GroundPlants_cell_','RocksAndWood_cell_')) and math.sqrt(sum(max(lo[j]-camera.location[j],0,camera.location[j]-hi[j])**2 for j in range(3)))>15:o.hide_render=True
        image_path=OUT/(ident+'.png');s.render.image_settings.file_format='PNG';s.render.filepath=str(image_path);bpy.ops.render.render(write_still=True)
        for name,value in hidden.items():bpy.data.objects[name].hide_render=value
        # Reset all far cells to original source visibility before next exact query.
        for obj in index_raw['objects']:
            if obj['name'] in bpy.data.objects:bpy.data.objects[obj['name']].hide_render=bool(obj.get('hidden_render',False))
        vfov=math.degrees(2*math.atan((36/(640/360))/(2*lens)))
        views.append({'id':ident,'calibration_state':state,'position':inverse(v['xyz']),'target':inverse(v['look_at']),
                      'fov_y_deg':vfov,'lens_mm':lens,'lens_sensor':'36mm horizontal / 16:9','azimuth_deg':v['azimuth_deg'],'elevation_deg':v['elevation_deg'],
                      'visibility':v['visibility'],'geometry':v['geometry'],'image':str(image_path),
                      'scope':'Finite stationary proposal measured at this calibration pose only; new actor poses/timing/track require recheck'})
    print('CAMERA_VIEWS',state,len(selected),flush=True)
dump('view_search_details.json',search_receipts);dump('camera_catalog.json',{'views':views,'calibration_states':calibrations})
assert all(any(v['calibration_state']==st[0] for v in views) for st in states),'Missing stationary proposals for one action state'
package={'schema':'shared_local_studio.v1','source_blend':str(source),'source_sha256':source_hash,
    'origin_blender':origin,'coordinates':'WorldOS Y-up; Blender=origin+[x,-z,y]; map-up=-Z',
    'units':'1 scene unit=1m is an engineering assumption, not physical calibration',
    'representation':'Exact kitchen pin geometry: elongated UV body, ellipsoid head, +Y white face marker, Wave Texture/Color Ramp stripes, invisible central grip; orange A, green B, blue C',
    'actor_sizes':{a['id']:[.44,1.72,.44] for a in baseline['groups'][0]['actors']},
    'anchors':anchors,'routes':[dict(id=r['id'],from_anchor=r['from'],to_anchor=r['to'],length=round(r['length'],3)) for r in routes],
    'route_details_ref':str(OUT/'navigation_details.json'),'interaction':interaction,
    'camera_views':[{k:v for k,v in view.items() if k not in ('visibility','geometry')}|{'minimum_sampled_visibility':view['visibility']['visible_ratio']} for view in views],
    'camera_details_ref':str(OUT/'camera_catalog.json'),
    'required_rechecks':'Both directors choose timing and blocking; any new plan must be rechecked against actual full forest and rendered frames. Finite proposals do not certify new trajectories.',
    'known_bad_camera':{'position':inverse(bad),'reason':regression['harness_geometry'],'rule':'Do not use as a shooting station'}}
dump('shared_studio.json',package)
reused=['camera_agent/planning/scene_index.py','camera_agent/blender/trajectory_verifier.py','camera_agent/blender/observation_geometry.py','camera_agent/blender/view_search.py','camera_agent/planning/view_proposals.py']
dump('reuse_evidence.json',{'harness':str(HARNESS),'directly_imported':{name:hashlib.sha256((HARNESS/name).read_bytes()).hexdigest() for name in reused},
    'new_experiment_code':['local region selection','actor proxy navigation/interaction catalog','shared studio packaging'],
    'original_source_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==source_hash,
    'local_environment_mesh_records':len(records),'global_scene_index_objects':len(index_raw['objects']),
    'camera_proposals':len(views),'navigation_routes':len(routes),'shared_package_sha256':hashlib.sha256((OUT/'shared_studio.json').read_bytes()).hexdigest()})
print('SHARED_STUDIO_READY',len(views),len(routes),flush=True)
