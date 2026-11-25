"""Blender worker: actual capsule readback, finite camera solving and pixel cache."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import argparse
import hashlib
import json
import math
import time
import bpy
from mathutils import Vector, Matrix
from types import SimpleNamespace
from studio_config import load_config
from season.model_job import digest
from season.camera_envelope import swept_target_corners


class Stage:
    def __init__(self, output, studio_dir):
        self.output = Path(output)
        self.config = load_config()
        self.studio = json.loads((Path(studio_dir)/'shared_studio.json').read_text())
        sys.path.insert(0, str(self.config['camera_harness']))
        sys.path.insert(0, str(ROOT/'experiments/forest_capsules'))
        from capsules import pin, material
        from camera_agent.blender.trajectory_verifier import _collision_meshes, _evaluate_camera_containment, _verify_camera_segment
        from camera_agent.blender.observation_geometry import assembly_visibility
        from camera_agent.blender.view_search import search_views
        self.meshes, self.containment, self.segment = _collision_meshes, _evaluate_camera_containment, _verify_camera_segment
        self.visibility, self.search_views = assembly_visibility, search_views
        source = Path(self.studio['source_blend'])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == self.studio['source_sha256']
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
        self.scene = s = bpy.context.scene
        s.frame_set(1)
        self.source_hash = self.studio['source_sha256']
        self.roots = {a: pin(a, color) for a, color in zip(('A','B','C'), ((.98,.36,.04),(.15,.75,.20),(.035,.45,.95)))}
        self.grips = {}
        for a in self.roots:
            empty = bpy.data.objects.new('GRIP_'+a, None)
            s.collection.objects.link(empty)
            self.grips[a] = empty
        def cube(name, size, position, color):
            bpy.ops.mesh.primitive_cube_add(size=1)
            obj = bpy.context.object
            obj.name = name; obj.scale = (size[0],size[2],size[1]); obj.location = position
            obj.data.materials.append(material(name, color))
            return obj
        for table in self.studio['interaction']['tables']:
            cube('STAGE_'+table['id'], table['size_m'], self.bridge(table['position']), (.4,.3,.18))
        self.box = cube('PROP_box', self.studio['interaction']['box_size_m'], self.bridge(self.studio['interaction']['pickup_box']), (1,.7,.04))
        self.camera = bpy.data.objects.new('SEASON_CAMERA', bpy.data.cameras.new('SEASON_CAMERA'))
        s.collection.objects.link(self.camera); s.camera = self.camera
        self.camera.rotation_mode = 'QUATERNION'
        self.camera.data.sensor_fit='HORIZONTAL';self.camera.data.sensor_width=36
        self.camera.data.clip_start=.05;self.camera.data.clip_end=500
        s.render.resolution_x=640;s.render.resolution_y=360;s.render.resolution_percentage=100
        s.render.engine='BLENDER_EEVEE';s.eevee.taa_render_samples=2;s.render.use_motion_blur=False
        s.render.image_settings.file_format='PNG';s.render.fps=24
        bpy.context.view_layer.update()
        self.bounds = {}
        for obj in s.objects:
            if obj.type=='MESH' and not obj.name.startswith(('A_','B_','C_','PROP_')):
                points = [obj.matrix_world@Vector(v) for v in obj.bound_box]
                self.bounds[obj.name] = ([min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)])
        origin=self.studio['origin_blender'];self.roi=([origin[0]-8,origin[1]-8,origin[2]-.5],[origin[0]+8,origin[1]+8,origin[2]+5])
        binding={'source_scene_sha256':self.source_hash,'origin_blender':origin,'verified_camera_volume':[self.roi[0],self.roi[1]]}
        binding_path=self.output/'stage_binding.json'
        if binding_path.exists():assert json.loads(binding_path.read_text())==binding,'Stage changed during production'
        else:binding_path.write_text(json.dumps(binding,indent=2))
        env=[]
        for name,(lo,hi) in self.bounds.items():
            if name in ('Terrain','Water') or name.startswith(('Trees_cell_','GroundPlants_cell_','RocksAndWood_cell_','STAGE_')):
                if all(hi[i]>=self.roi[0][i] and lo[i]<=self.roi[1][i] for i in range(3)):
                    env.append(bpy.data.objects[name])
        self.environment=self.meshes(bpy.context.evaluated_depsgraph_get(),env)
        self.body_obstacles=[r for r in self.environment if r['name'].startswith(('Trees_cell_','RocksAndWood_cell_','STAGE_'))]
        self.terrain=next(r['tree'] for r in self.environment if r['name']=='Terrain')
        self.culled=[]
        for name,(lo,hi) in self.bounds.items():
            if name.startswith(('Trees_cell_','GroundPlants_cell_','RocksAndWood_cell_')):
                distance=math.sqrt(sum(max(lo[i]-self.roi[1][i],self.roi[0][i]-hi[i],0)**2 for i in range(3)))
                if distance>20:self.culled.append(name)
        self.pixel_cache=self.output/'pixel_cache';self.pixel_cache.mkdir(exist_ok=True)
        self.check_cache={};self.body_cache={};self.rendered=0
        self.cache_binding=digest({'scene':self.source_hash,'culled':self.culled,'resolution':[640,360],'engine':'EEVEE','samples':2,'capsules':'kitchen_pin_v1'})

    def bridge(self,point):
        o=self.studio['origin_blender'];return [o[0]+point[0],o[1]-point[2],o[2]+point[1]]

    def pose(self,row):
        for a,values in row['actors'].items():
            self.roots[a].location=values['position'];self.roots[a].rotation_euler=(0,0,values['yaw'])
            self.grips[a].location=values['anchor']
        self.box.location=row['props']['box']['position']
        bpy.context.view_layer.update()

    def clear(self,point,records):
        blockers=[];nearest=float('inf')
        for record in records:
            distance=record['tree'].find_nearest(Vector(point))[3]
            nearest=min(nearest,distance)
            if distance<.15 or all(record['min'][i]<=point[i]<=record['max'][i] for i in range(3)):
                value=self.containment(point,record,clearance=.15)
                if value['inside'] is not False:blockers.append({'object':record['name'],'reason':value['reason']})
        return {'clear':not blockers,'blockers':blockers,'surface_distance':nearest,'radius':.15,'clearance_enforcement':'required'}

    def world_key(self,row,camera,subjects):
        # No timestamps/captions: only exact visible transforms and required checks.
        return digest({'binding':self.cache_binding,'actors':{a:[v['position'],v['yaw']] for a,v in row['actors'].items()},
                       'box':row['props']['box']['position'],'camera':camera,'subjects':subjects})

    def validate_body(self,motion):
        errors=[];max_readback=0.;terrain_error=0.
        previous=None
        for row in motion['samples']+[motion['endpoint']]:
            self.pose(row)
            for a,value in row['actors'].items():
                actual=list(self.roots[a].matrix_world.translation)
                max_readback=max(max_readback,math.dist(actual,value['position']))
                prior=previous['actors'][a]['position'] if previous else value['position']
                key=digest([prior,value['position']])
                if key in self.body_cache:continue
                hit=self.terrain.ray_cast(Vector((actual[0],actual[1],30)),Vector((0,0,-1)),80)
                error=abs(actual[2]-hit[0].z) if hit[0] is not None else float('inf')
                terrain_error=max(terrain_error,error)
                if error>.02:errors.append({'frame':row['frame'],'actor':a,'terrain_error':error})
                for h in [.25+1.25*j/7 for j in range(8)]:
                    first=[prior[0],prior[1],prior[2]+h];last=[actual[0],actual[1],actual[2]+h]
                    check=self.segment(first,last,self.body_obstacles,clearance=.42)
                    if not check['valid']:errors.append({'frame':row['frame'],'actor':a,'body_check':check});break
                self.body_cache[key]=True
            max_readback=max(max_readback,math.dist(self.box.matrix_world.translation,row['props']['box']['position']))
            previous=row
        assert max_readback<1e-5,max_readback
        return {'status':'pass' if not errors else 'fail','errors':errors[:20],'frames':len(motion['samples']),
                'max_position_readback_error':max_readback,'max_terrain_error':terrain_error,
                'scope':'Declared Trees/RocksAndWood/STAGE sphere proxy; excludes GroundPlants and gait/physical grasp'}

    def check_pose(self,row,camera,subjects,previous_camera=None):
        if any(not self.roi[0][i]+.15 <= camera['position'][i] <= self.roi[1][i]-.15 for i in range(3)):
            return {'pass':False,'frame':row['frame'],'reason':'camera_left_verified_local_volume',
                    'position':camera['position'],'verified_roi':self.roi}
        key=self.world_key(row,camera,subjects)
        if key in self.check_cache:return {**self.check_cache[key],'frame':row['frame']}
        self.pose(row);self.set_camera(camera)
        deps=bpy.context.evaluated_depsgraph_get()
        objects=[o for o in self.scene.objects if o.type=='MESH' and o.name.startswith(('A_','B_','C_','PROP_box'))]
        dynamic=self.meshes(deps,objects)
        geometry=self.clear(camera['position'],self.environment+dynamic)
        target_names=[a+'_head' if a!='box' else 'PROP_box' for a in subjects]
        target_trees={r['name']:r['tree'] for r in dynamic if r['name'] in target_names}
        visibility=self.visibility(self.scene,self.camera,target_trees,(64,36))
        if visibility['needs_finer_sampling']:visibility=self.visibility(self.scene,self.camera,target_trees,(128,72))
        if visibility['needs_finer_sampling']:visibility=self.visibility(self.scene,self.camera,target_trees,(256,144))
        bad=[a for a,v in visibility['visible_ratio'].items() if v is None or v<.5]
        result={'pass':geometry['clear'] and not bad and not visibility['needs_finer_sampling'],
                'geometry':geometry,'bad_targets':bad,'visibility':visibility,'frame':row['frame']}
        self.check_cache[key]=result
        return result

    def set_camera(self,camera):
        self.camera.location=camera['position']
        self.camera.rotation_quaternion=(Vector(camera['target'])-self.camera.location).to_track_quat('-Z','Y')
        self.camera.data.lens=camera['lens_mm']
        bpy.context.view_layer.update()

    def solve_scene(self,directory,plan,motion):
        directory=Path(directory);body=self.validate_body(motion)
        (directory/'body_checks.json').write_text(json.dumps(body,indent=2))
        if body['status']!='pass':return {'status':'action_repair_required','body':body}
        selected=[];failures=[];checks=0;cache_hits=0
        for shot in plan['shots']:
            first,last=round(shot['start_s']*24),round(shot['end_s']*24)
            middle=min(len(motion['samples'])-1,(first+last)//2)
            row=motion['samples'][middle];self.pose(row)
            targets=[bpy.data.objects[a+'_head' if a!='box' else 'PROP_box'] for a in shot['subjects']]
            records=self.meshes(bpy.context.evaluated_depsgraph_get(),targets)
            dynamic=self.meshes(bpy.context.evaluated_depsgraph_get(),[o for o in self.scene.objects if o.type=='MESH' and o.name.startswith(('A_','B_','C_','PROP_box'))])
            request={'lens_mm':shot['lens_mm'],'projected_height':shot['projected_height'],
                     'azimuths_deg':shot['allowed_azimuths_deg'],'elevations_deg':shot['allowed_elevations_deg'],
                     'max_views':6,'require_full_frame':True,'position_bounds':{'min':self.roi[0],'max':self.roi[1]}}
            reference=row['actors'][shot['follow_actor']]['position'] if shot['motion']=='follow_actor' else None
            envelope=swept_target_corners(motion['samples'][first:last],shot['subjects'],
                     self.studio['interaction']['box_size_m'],shot['follow_actor'],reference)
            # Geometry-only adapters: search uses the full motion envelope for
            # framing, and the real midpoint BVHs/scene for proposal visibility.
            framing_targets=[]
            for target in targets:
                mesh=SimpleNamespace(vertices=[SimpleNamespace(co=Vector(p)) for p in envelope[target.name]])
                evaluated=SimpleNamespace(matrix_world=Matrix.Identity(4),to_mesh=lambda m=mesh:m,to_mesh_clear=lambda:None)
                framing_targets.append(SimpleNamespace(name=target.name,evaluated_get=lambda deps,e=evaluated:e))
            # Exhaust the director's declared directions. A midpoint top-six
            # shortlist can discard a view that is better over the full motion.
            views=[];direction_receipts=[];rejected=[];hard_valid=0
            for azimuth in shot['allowed_azimuths_deg']:
                directional={**request,'azimuths_deg':[azimuth],'max_views':len(shot['allowed_elevations_deg'])}
                found,receipt=self.search_views(self.scene,self.camera,framing_targets,[(r['name'],r['tree'],r['closed']) for r in records],
                               lambda point:self.clear(point,self.environment+dynamic),directional)
                views+=found;rejected+=receipt['rejected'];hard_valid+=receipt['hard_valid_count']
                direction_receipts.append({'azimuth_deg':azimuth,'hard_valid_count':receipt['hard_valid_count'],'selected_count':len(found)})
            search={'request':request,'hard_valid_count':hard_valid,'rejected':rejected,'direction_receipts':direction_receipts,
                    'scope':'All declared finite azimuth/elevation pairs; swept framing envelope, midpoint proposal ranking, full-interval acceptance'}
            views.sort(key=lambda v:-v['score'])
            attempts=[];chosen=None
            for candidate in views:
                cameras=[];bad=None;prev=None
                for i in range(first,last):
                    frame=motion['samples'][i]
                    delta=[0,0,0] if reference is None else [a-b for a,b in zip(frame['actors'][shot['follow_actor']]['position'],reference)]
                    cam={'position':[a+b for a,b in zip(candidate['xyz'],delta)],
                         'target':[a+b for a,b in zip(candidate['look_at'],delta)],'lens_mm':shot['lens_mm']}
                    key=self.world_key(frame,cam,shot['subjects']);cache_hits+=key in self.check_cache
                    check=self.check_pose(frame,cam,shot['subjects']);checks+=1
                    if not check['pass']:bad=check;break
                    if prev and math.dist(prev['position'],cam['position'])>1e-8:
                        segment=self.segment(prev['position'],cam['position'],self.environment,clearance=.15)
                        if not segment['valid']:bad={'frame':frame['frame'],'segment':segment};break
                    cameras.append(cam);prev=cam
                attempts.append({'azimuth_deg':candidate['azimuth_deg'],'elevation_deg':candidate['elevation_deg'],
                                 'reference_position':candidate['xyz'],'reference_target':candidate['look_at'],'failure':bad})
                if bad is None:
                    chosen={'shot':shot,'frames':cameras,'candidate':{k:v for k,v in candidate.items() if k not in ('visibility','geometry')}}
                    break
            if chosen is None:
                failures.append({'shot':shot['id'],'intent':shot,'attempts':attempts,
                                 'search':search,'reason':'No allowed finite candidate passed the actual complete interval'})
                continue
            selected.append(chosen)
            print('SHOT_SOLVED',plan['id'],shot['id'],len(chosen['frames']),flush=True)
        report={'status':'pass' if not failures else 'photography_repair_required','failures':failures,
                'frames_checked_including_rejected':checks,'exact_pose_check_cache_hits':cache_hits,
                'scope':'All encoded frames for accepted finite candidates; full current Forest raycasts; not semantic or physical certification'}
        (directory/'camera_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        if failures:return report
        (directory/'solved_camera.json').write_text(json.dumps(selected,ensure_ascii=False,separators=(',',':')))
        frame_keys=[];unique=set();representatives=[]
        for selection in selected:
            shot=selection['shot'];first=round(shot['start_s']*24)
            for i,cam in enumerate(selection['frames']):
                row=motion['samples'][first+i]
                key=self.world_key(row,cam,[]) # Pixels do not depend on the check's subject selection.
                frame_keys.append(key);unique.add(key)
                target=self.pixel_cache/(key+'.png')
                if not target.exists():
                    self.pose(row);self.set_camera(cam)
                    for name in self.culled:bpy.data.objects[name].hide_render=True
                    self.scene.render.filepath=str(target)
                    bpy.ops.render.render(write_still=True)
                    for name in self.culled:bpy.data.objects[name].hide_render=False
                    self.rendered+=1
                    if self.rendered%25==0:print('UNIQUE_PIXELS_RENDERED',self.rendered,flush=True)
                if i==len(selection['frames'])//2:representatives.append({'shot':shot['id'],'file':str(target),'intent':shot['intent']})
        assert len(frame_keys)==round(motion['diagnostics']['duration_s']*24)
        manifest={'scene':plan['id'],'fps':24,'frame_count':len(frame_keys),'frame_keys':frame_keys,
                  'unique_pixel_states':len(unique),'representative_frames':representatives,
                  'cache_binding':self.cache_binding,'render_omitted_background':self.culled,'source_scene_sha256':self.source_hash}
        (directory/'frames.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
        print('SCENE_RENDERED',plan['id'],len(frame_keys),len(unique),flush=True)
        return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True);parser.add_argument('--prior-dir',required=True);parser.add_argument('--episode',required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    output=Path(args.output);stage=Stage(output,args.prior_dir)
    plan=json.loads((output/f'{args.episode}_camera_plan.json').read_text())
    reports=[];failed=False
    for scene in plan['scenes']:
        directory=output/'scenes'/scene['id']
        if (directory/'frames.json').exists():
            # A changed photography plan gets a new render even if old pixels remain reusable.
            solved=json.loads((directory/'solved_camera.json').read_text())
            if [s['shot'] for s in solved]==scene['shots']:
                reports.append({'scene':scene['id'],'status':'cached_complete'});continue
        motion=json.loads((directory/'motion.json').read_text())
        report=stage.solve_scene(directory,scene,motion);reports.append({'scene':scene['id'],**report})
        if report['status']!='pass':
            failed=True
    (output/f'{args.episode}_production_checks.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    if failed:raise SystemExit(2)
    print('EPISODE_GEOMETRY_AND_PIXELS_COMPLETE',args.episode,flush=True)


if __name__=='__main__':main()
