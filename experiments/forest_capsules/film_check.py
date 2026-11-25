import sys,json,math,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from paths import OUT,HARNESS
sys.path.insert(0,str(HARNESS))
import bpy
from mathutils import Vector,Quaternion
from camera_agent.blender.trajectory_importer import import_camera_tool_result
from camera_agent.blender.trajectory_verifier import _collision_meshes,_evaluate_camera_containment,_verify_camera_segment
from camera_agent.blender.observation_geometry import assembly_visibility
P=OUT/'project';plan=json.loads((P/'camera_plan.json').read_text());specs={s['id']:s for s in plan['shots']};samples=json.loads((OUT/'camera_samples.json').read_text());motion=json.loads((OUT/'motion_samples.json').read_text());manifest=json.loads((OUT/'actor_clip_manifest.json').read_text())
source=Path(manifest['animated_scene']);before=hashlib.sha256(source.read_bytes()).hexdigest();assert before==manifest['scene_version']
bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
import_camera_tool_result(str(OUT/'camera_tool_result.json'),str(OUT/'candidate_scene.blend'));s=bpy.context.scene
def bounds(o):
    p=[o.matrix_world@Vector(v) for v in o.bound_box];return [min(x[i] for x in p) for i in range(3)],[max(x[i] for x in p) for i in range(3)]
lo=[min(r['location'][i] for r in samples)-.5 for i in range(3)];hi=[max(r['location'][i] for r in samples)+.5 for i in range(3)]
objects=[]
for obj in s.objects:
    if obj.type!='MESH' or not (obj.name.startswith(('Trees_cell_','GroundPlants_cell_','RocksAndWood_cell_','STAGE_')) or obj.name in ['Terrain','Water']):continue
    a,b=bounds(obj)
    if all(b[i]>=lo[i] and a[i]<=hi[i] for i in range(3)):objects.append(obj)
s.frame_set(1);environment=_collision_meshes(bpy.context.evaluated_depsgraph_get(),objects)
checks=[];failures=[];max_actor_error=0;max_camera_error=0;max_axis_error=0;previous=None
for row,m in zip(samples,motion):
    f=row['frame'];s.frame_set(f);deps=bpy.context.evaluated_depsgraph_get();camera=s.camera
    assert camera.name==row['camera_name'],('active camera mismatch',f,camera.name,row['camera_name'])
    actual=camera.evaluated_get(deps);pos=list(actual.matrix_world.translation);max_camera_error=max(max_camera_error,math.dist(pos,row['location']))
    dot=abs(actual.matrix_world.to_quaternion().normalized().dot(Quaternion(row['rotation_quaternion']).normalized()))
    max_axis_error=max(max_axis_error,2*math.acos(min(1,dot)))
    for id,a in m['actors'].items():max_actor_error=max(max_actor_error,math.dist(bpy.data.objects['PREVIS_'+id].evaluated_get(deps).matrix_world.translation,a['position']))
    max_actor_error=max(max_actor_error,math.dist(bpy.data.objects['PROP_box'].evaluated_get(deps).matrix_world.translation,m['props']['box']['position']))
    dynamic=_collision_meshes(deps,[o for o in s.objects if o.type=='MESH' and o.name.startswith(('CHAR-','PROP_box'))])
    collisions=[]
    for record in environment+dynamic:
        d=record['tree'].find_nearest(Vector(pos))[3]
        if d<.15 or all(record['min'][i]<=pos[i]<=record['max'][i] for i in range(3)):
            result=_evaluate_camera_containment(pos,record,clearance=.15)
            if result['inside'] is not False:collisions.append({'object':record['name'],**result})
    segment=None
    if previous and previous['shot']==row['shot']:segment=_verify_camera_segment(previous['location'],pos,environment,clearance=.15)
    names=[id+'_head' for id in row['required_actors']]+(['PROP_box'] if row['require_box'] else [])
    target_records=_collision_meshes(deps,[bpy.data.objects[name] for name in names]);trees={r['name']:r['tree'] for r in target_records}
    vis=assembly_visibility(s,camera,trees,(64,36))
    if vis['needs_finer_sampling']:vis=assembly_visibility(s,camera,trees,(128,72))
    if vis['needs_finer_sampling']:vis=assembly_visibility(s,camera,trees,(256,144))
    bad=[name for name,value in vis['visible_ratio'].items() if value is None or value<.5]
    result={'frame':f,'time_s':(f-1)/24,'shot':row['shot'],'camera':camera.name,'position':pos,'geometry_collisions':collisions,
            'environment_segment':segment,'visibility':vis}
    checks.append(result)
    if collisions or segment and not segment['valid'] or bad or vis['needs_finer_sampling']:
        failures.append({'frame':f,'time_s':(f-1)/24,'shot':row['shot'],'geometry_collisions':collisions,'bad_visible_targets':bad,'visibility':vis,'segment':segment})
    previous=row
    if f%48==0:print('CHECKED',f,'failures',len(failures),flush=True)
assert max_actor_error<1e-5 and max_camera_error<1e-5 and max_axis_error<.001,(max_actor_error,max_camera_error,max_axis_error)
assert hashlib.sha256(source.read_bytes()).hexdigest()==before
report={'status':'pass' if not failures else 'needs_photography_repair','frames':len(samples),'failures':failures,
        'max_actor_prop_readback_error':max_actor_error,'max_camera_position_error':max_camera_error,'max_camera_quaternion_error_rad':max_axis_error,
        'motion_source_unchanged':True,'scope':'Full-forest foreground rays; sampled required head/prop visibility >=0.5 and >=4 hits, adaptive grid up to256x144; static mesh camera sphere and straight-segment clearance; dynamic actor collisions at encoded frames only; not semantic/grasp/optical certification or native finalize'}
(OUT/'film_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(OUT/'film_frame_measurements.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')
# Geometry/visibility checks above use the full forest; only distant background is omitted for RGB.
radius=max(15,math.ceil(max(math.dist(c['location'],a['position'])+1.72 for c,m in zip(samples,motion) for a in m['actors'].values())+1))
culled=[]
for obj in s.objects:
    if obj.type!='MESH' or not obj.name.startswith(('Trees_cell_','GroundPlants_cell_','RocksAndWood_cell_')):continue
    a,b=bounds(obj)
    distance=min(math.sqrt(sum(max(a[i]-r['location'][i],0,r['location'][i]-b[i])**2 for i in range(3))) for r in samples)
    if distance>radius:obj.hide_render=True;culled.append(obj.name)
(OUT/'film_render_scope.json').write_text(json.dumps({'radius':radius,'excluded_distant_background':culled,'scope':'Only render background optimization; all geometric/visibility checks used full forest and all actor geometry lies within this radius'},indent=2)+'\n')
s.render.resolution_x=768;s.render.resolution_y=432;s.render.resolution_percentage=100;s.render.engine='BLENDER_EEVEE';s.eevee.taa_render_samples=8;s.render.image_settings.file_format='PNG'
representative={round((shot['start_s']+shot['end_s'])/2*24)+1 for shot in plan['shots']}
representative|={min(len(samples),max(1,round(e['t']*24)+1)) for e in json.loads((P/'action_plan.json').read_text())['events']}
representative.add(len(samples));representative|={f['frame'] for f in failures[::max(1,len(failures)//3)]}
for f in sorted(representative):
    s.frame_set(f);s.render.filepath=str(OUT/f'film_frame_{f:04d}.png');bpy.ops.render.render(write_still=True)
print('FILM_CHECK',report['status'],len(failures),flush=True)
sys.exit(0 if not failures else 2)
