import sys,json,math
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from paths import OUT,HARNESS
sys.path.insert(0,str(HARNESS))
import bpy
from mathutils import Vector
from camera_agent.blender.trajectory_verifier import _collision_meshes
from camera_agent.blender.observation_geometry import assembly_visibility
P=OUT/'project';studio=json.loads((P/'shared_studio.json').read_text());origin=studio['origin_blender'];views={v['id']:v for v in studio['camera_views']}
bpy.ops.wm.open_mainfile(filepath=str(OUT/'motion.blend'),load_ui=False,use_scripts=False);s=bpy.context.scene;s.timeline_markers.clear()
data=bpy.data.cameras.new('REPAIR_PROBE');camera=bpy.data.objects.new('REPAIR_PROBE',data);s.collection.objects.link(camera);s.camera=camera;data.sensor_fit='VERTICAL';data.sensor_height=24;data.clip_start=.05;data.clip_end=500;s.render.resolution_x=640;s.render.resolution_y=360
def bridge(p):return [origin[0]+p[0],origin[1]-p[2],origin[2]+p[1]]
rows=[]
for shot,ids,times,stations in [
 ('sh02',['CHAR-0001'],[2.375,3,3.875,4.125,4.375],['pickup_view_1','pickup_view_2','pickup_view_3']),
 ('sh03',['CHAR-0001','CHAR-0002','CHAR-0003'],[4.5,5.25,6.125,6.5,7.25,8.083333333],['establish_view_1','establish_view_2','pickup_view_2','pickup_view_3','handover_view_2'])]:
 for station in stations:
  v=views[station];fov=v['fov_y_deg'] if shot=='sh02' else views['establish_view_1']['fov_y_deg'];points=[]
  for t in times:
   s.frame_set(round(t*24)+1);camera.location=bridge(v['position']);camera.rotation_euler=(Vector(bridge(v['target']))-camera.location).to_track_quat('-Z','Y').to_euler();data.lens=24/(2*math.tan(math.radians(fov)/2));bpy.context.view_layer.update()
   records=_collision_meshes(bpy.context.evaluated_depsgraph_get(),[bpy.data.objects[id+'_head'] for id in ids]+[bpy.data.objects['PROP_box']])
   vis=assembly_visibility(s,camera,{r['name']:r['tree'] for r in records},(128,72))
   if vis['needs_finer_sampling']:vis=assembly_visibility(s,camera,{r['name']:r['tree'] for r in records},(256,144))
   points.append({'t':t,'visible_ratio':vis['visible_ratio'],'target_only_hits':vis['target_only_hits'],'same_ray_occluders':vis['same_ray_occluders']})
  rows.append({'shot':shot,'station_id':station,'fov_y_deg':fov,'samples':points})
(OUT/'repair_survey.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');print('REPAIR_OPTIONS_MEASURED',len(rows),flush=True)
