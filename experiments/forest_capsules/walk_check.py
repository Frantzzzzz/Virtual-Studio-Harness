"""Actual baked roots: terrain support and declared static-obstacle capsule paths."""
import sys,json,math
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from paths import OUT,HARNESS
sys.path.insert(0,str(HARNESS))
import bpy
from mathutils import Vector
from camera_agent.blender.trajectory_verifier import _collision_meshes,_verify_camera_segment,_evaluate_camera_containment
data=json.loads((OUT/'blender_motion_readback.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(OUT/'motion.blend'),load_ui=False,use_scripts=False)
s=bpy.context.scene;s.frame_set(1);deps=bpy.context.evaluated_depsgraph_get()
lo=[min(p[i] for row in data for p in row['actors'].values())-1 for i in range(3)];hi=[max(p[i] for row in data for p in row['actors'].values())+2 for i in range(3)]
objects=[]
for obj in s.objects:
 if obj.type!='MESH' or not obj.name.startswith(('Trees_cell_','RocksAndWood_cell_','STAGE_')):continue
 corners=[obj.matrix_world@Vector(v) for v in obj.bound_box]
 if all(max(v[i] for v in corners)>=lo[i] and min(v[i] for v in corners)<=hi[i] for i in range(3)):objects.append(obj)
obstacles=_collision_meshes(deps,objects);terrain=_collision_meshes(deps,[bpy.data.objects['Terrain']])[0]['tree']
ground=[];bad=[];centres=[.25+1.25*j/7 for j in range(8)];radius=.27
for index,row in enumerate(data):
 for ident,pos in row['actors'].items():
  hit=terrain.ray_cast(Vector((pos[0],pos[1],30)),Vector((0,0,-1)),80)
  assert hit[0] is not None
  ground.append(pos[2]-hit[0].z)
  if index:
   a=data[index-1]['actors'][ident];b=pos
   if math.dist(a,b)>1e-9:
    for h in centres:
     check=_verify_camera_segment([a[0],a[1],a[2]+h],[b[0],b[1],b[2]+h],obstacles,clearance=radius+.15)
     if not check['valid']:bad.append({'frame':row['frame'],'actor':ident,'height':h,'check':check})
assert max(abs(v) for v in ground)<.02,('Terrain support error',min(ground),max(ground))
report={'status':'pass' if not bad else 'fail','frames':len(data),'actors':3,'terrain_root_error_range':[min(ground),max(ground)],'failures':bad,
 'scope':'Actual baked root segments against declared Trees/RocksAndWood/STAGE meshes with 8-sphere vertical proxy and 0.15 surface margin; excludes GroundPlants category (not a semantic solid/vegetation guarantee), original high-detail scene, physical gait and between-frame terrain support extrema'}
(OUT/'walk_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('WALK_CHECK',report['status'],min(ground),max(ground),len(bad),flush=True)
assert not bad,bad[:1]
