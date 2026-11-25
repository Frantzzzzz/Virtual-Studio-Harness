"""Kitchen capsule animation and actual-scene observation for the photography director."""
import sys,json,math,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from paths import OUT,HARNESS
sys.path.insert(0,str(HARNESS))
import bpy
from mathutils import Vector
from capsules import pin,material,COLORS
from camera_agent.blender.trajectory_verifier import _collision_meshes,_evaluate_camera_containment
from camera_agent.blender.observation_geometry import assembly_visibility
P=OUT/'project';studio=json.loads((P/'shared_studio.json').read_text());plan=json.loads((P/'action_plan.json').read_text());rows=json.loads((OUT/'motion_samples.json').read_text());native=json.loads((OUT/'native_motion_samples.json').read_text())
source=Path(studio['source_blend']);before=hashlib.sha256(source.read_bytes()).hexdigest();assert before==studio['source_sha256']
bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
s=bpy.context.scene;s.frame_set(1);original={o.name:[list(r) for r in o.matrix_world] for o in s.objects};origin=studio['origin_blender']
def bridge(p):return [origin[0]+p[0],origin[1]-p[2],origin[2]+p[1]]
def inverse(p):return [p[0]-origin[0],p[2]-origin[2],-(p[1]-origin[1])]
actors={id:pin(id,color) for id,color in COLORS.items()};grips={}
for id in actors:
    obj=bpy.data.objects.new('GRIP_'+id,None);s.collection.objects.link(obj);grips[id]=obj
def cube(name,size,pos,color):
    bpy.ops.mesh.primitive_cube_add(size=1);o=bpy.context.object;o.name=name;o.scale=(size[0],size[2],size[1]);o.location=pos;o.data.materials.append(material(name,color));return o
for t in studio['interaction']['tables']:cube('STAGE_'+t['id'],t['size_m'],bridge(t['position']),(.4,.3,.18))
box=cube('PROP_box',studio['interaction']['box_size_m'],rows[0]['props']['box']['position'],(1,.7,.04))
for row in rows:
    f=row['frame']
    for id,a in row['actors'].items():
        actors[id].location=a['position'];actors[id].rotation_euler=(0,0,a['yaw']);grips[id].location=a['grip']
        actors[id].keyframe_insert('location',frame=f);actors[id].keyframe_insert('rotation_euler',frame=f);grips[id].keyframe_insert('location',frame=f)
    box.location=row['props']['box']['position'];box.keyframe_insert('location',frame=f)
for obj in list(actors.values())+list(grips.values())+[box]:
    for layer in obj.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:key.interpolation='LINEAR'
s.render.fps=24;s.frame_start=1;s.frame_end=len(rows);s.timeline_markers.clear()
s.render.resolution_x=640;s.render.resolution_y=360;s.render.resolution_percentage=100;s.render.engine='BLENDER_EEVEE';s.eevee.taa_render_samples=8;s.render.use_motion_blur=False
def dump(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
measured=[];error=0;facing_error=0
for row in rows:
    s.frame_set(row['frame']);deps=bpy.context.evaluated_depsgraph_get();r={'frame':row['frame'],'actors':{},'grips':{},'box':list(box.evaluated_get(deps).matrix_world.translation)}
    error=max(error,math.dist(r['box'],row['props']['box']['position']))
    for id,a in row['actors'].items():
        actual=actors[id].evaluated_get(deps);r['actors'][id]=list(actual.matrix_world.translation);r['grips'][id]=list(grips[id].evaluated_get(deps).matrix_world.translation)
        error=max(error,math.dist(r['actors'][id],a['position']),math.dist(r['grips'][id],a['grip']))
        forward=actual.matrix_world.to_quaternion()@Vector((0,1,0));facing_error=max(facing_error,forward.angle(Vector((-math.sin(a['yaw']),math.cos(a['yaw']),0))))
    measured.append(r)
assert error<1e-5 and facing_error<.001,(error,facing_error)
assert {n:[list(r) for r in bpy.data.objects[n].matrix_world] for n in original}==original
assert hashlib.sha256(source.read_bytes()).hexdigest()==before
dump('blender_motion_readback.json',measured);dump('blender_motion_checks.json',{'frames':len(rows),'max_position_error':error,'max_facing_error_rad':facing_error,'source_sha256':before,'original_objects_unchanged':True,'representation':'Kitchen pin, no arms/legs/rig; grip Empty world positions measured, not grasp physics'})
s.frame_set(1);bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'motion.blend'))
motion_sha=hashlib.sha256((OUT/'motion.blend').read_bytes()).hexdigest()
manifest={'animated_scene':str(OUT/'motion.blend'),'scene_version':motion_sha,'fps':24,'source_start_frame':1,'frame_count':len(rows),
          'entities':{id:{'root':'object:PREVIS_'+id,'members':['object:'+id+'_body','object:'+id+'_head','object:'+id+'_facing'],'grip':'object:GRIP_'+id} for id in actors},
          'prop':'object:PROP_box','events_ref':str(OUT/'ownership_events.json'),'measurements_ref':str(OUT/'blender_motion_readback.json')}
dump('actor_clip_manifest.json',manifest)
camera_data=bpy.data.cameras.new('SURVEY_CAMERA');camera=bpy.data.objects.new('SURVEY_CAMERA',camera_data);s.collection.objects.link(camera);s.camera=camera;camera_data.sensor_fit='VERTICAL';camera_data.sensor_height=24;camera_data.clip_start=.05;camera_data.clip_end=500
def set_camera(pos,target,fov):
    camera.location=bridge(pos);camera.rotation_euler=(Vector(bridge(target))-camera.location).to_track_quat('-Z','Y').to_euler();camera_data.lens=24/(2*math.tan(math.radians(fov)/2));bpy.context.view_layer.update()
ta,tb,tr,td=[e['t'] for e in plan['events']]
times={'establish':[0],'pickup':[max(0,ta-.25),ta,ta+.5],
       'handover':[tb-.25,tb,(tb+tr)/2,tr,tr+.5],
       'carry':[tr+.5,(tr+td)/2,td-1],'drop':[td-.5,td,min(td+.5,plan['duration_s']-1/24),plan['duration_s']-1/24]}
details=json.loads((OUT/'camera_catalog.json').read_text());observations=[];image_count=0
for view in studio['camera_views']:
    state=view['calibration_state']
    modes=['static','track_subject'] if state=='carry' else ['static']
    for mode in modes:
        record={'id':view['id']+'__'+mode,'station_id':view['id'],'mode':mode,'state':state,'samples':[]}
        for t in times[state]:
            f=max(1,min(len(rows),round(t*24)+1));s.frame_set(f);deps=bpy.context.evaluated_depsgraph_get()
            pos=list(view['position']);target=list(view['target'])
            if mode=='track_subject':
                reference=details['calibration_states']['carry']['actors']['CHAR-0002']['position'];current=native[f-1]['actors']['CHAR-0002']['position'];delta=[a-b for a,b in zip(current,reference)];pos=[a+b for a,b in zip(pos,delta)];target=[a+b for a,b in zip(target,delta)]
            set_camera(pos,target,view['fov_y_deg'])
            ids=['CHAR-0001','CHAR-0002','CHAR-0003'] if state=='establish' else ['CHAR-0001'] if state=='pickup' else ['CHAR-0001','CHAR-0002'] if state=='handover' else ['CHAR-0002']
            names=[id+'_head' for id in ids]+([] if state=='establish' else ['PROP_box'])
            target_records=_collision_meshes(deps,[bpy.data.objects[name] for name in names]);vis=assembly_visibility(s,camera,{r['name']:r['tree'] for r in target_records},(128,72))
            record['samples'].append({'frame':f,'t':(f-1)/24,'position':pos,'target':target,'visibility':vis})
        ratios=[v for row in record['samples'] for v in row['visibility']['visible_ratio'].values()]
        record['minimum_sampled_visibility']=min((v if v is not None else 0 for v in ratios),default=0)
        record['eligible_for_same_pose_samples']=record['minimum_sampled_visibility']>=.5
        observations.append(record)
    print('OBSERVED',view['id'],flush=True)
dump('motion_view_observations.json',observations)
(P/'motion_view_observations.json').write_text(json.dumps(observations,ensure_ascii=False,indent=2)+'\n')
(P/'actor_clip_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
# Actual-pose RGB evidence for one currently eligible proposal per phase.
for state in times:
    eligible=sorted([o for o in observations if o['state']==state and o['eligible_for_same_pose_samples']],key=lambda o:-o['minimum_sampled_visibility'])
    if not eligible:continue
    record=eligible[0];sample_row=record['samples'][len(record['samples'])//2];view=next(v for v in studio['camera_views'] if v['id']==record['station_id'])
    s.frame_set(sample_row['frame']);set_camera(sample_row['position'],sample_row['target'],view['fov_y_deg'])
    old_hide={o.name:o.hide_render for o in s.objects if o.name in original}
    for name in original:
        o=bpy.data.objects[name]
        if o.type=='MESH' and o.name.startswith(('Trees_cell_','GroundPlants_cell_','RocksAndWood_cell_')):
            pts=[o.matrix_world@Vector(v) for v in o.bound_box];lo=[min(p[i] for p in pts) for i in range(3)];hi=[max(p[i] for p in pts) for i in range(3)]
            if math.sqrt(sum(max(lo[i]-camera.location[i],0,camera.location[i]-hi[i])**2 for i in range(3)))>15:o.hide_render=True
    s.render.image_settings.file_format='PNG';s.render.filepath=str(OUT/('actual_'+state+'.png'));bpy.ops.render.render(write_still=True)
    for name,hide in old_hide.items():bpy.data.objects[name].hide_render=hide
print('BAKED_CAPSULES',len(rows),error,flush=True)
