"""Save an editable eight-minute animated blend and verify actual fcurve readback."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import argparse
import hashlib
import json
import math
import bpy
from mathutils import Vector,Quaternion
from season.blender_stage import Stage
from season.motion import quaternion_angle_error


def sparse_indices(values):
    result={0,len(values)-1}
    for i in range(1,len(values)):
        if values[i]!=values[i-1]:result.update((i-1,i))
    return sorted(result)


def bake(output,prior_dir,episode):
    output=Path(output);stage=Stage(output,prior_dir);s=stage.scene
    from camera_agent.motion.expert_route import build
    from camera_agent.motion import sample_motion
    from camera_agent.tool.camera_tool_result import normalize_camera_tool_result
    from camera_agent.harness.backends.sequence import compose
    from camera_agent.blender.trajectory_importer import import_camera_tool_result
    series=json.loads((output/'series_plan.json').read_text())
    outline=next(e for e in series['episodes'] if e['id']==episode)
    all_rows=[];candidates=[];intent={'shots':[]};expected_camera=[]
    for scene in outline['scenes']:
        directory=output/'scenes'/scene['id'];motion=json.loads((directory/'motion.json').read_text())
        all_rows+=motion['samples']
        solved=json.loads((directory/'solved_camera.json').read_text())
        for item in solved:
            spec=item['shot'];frames=item['frames'];count=len(frames);duration=count/24
            times=[i/24 for i in range(count+1)];expanded=frames+[frames[-1]]
            parameters={'position':{'times_s':times,'values_m':[v['position'] for v in expanded]},
                        'aim':{'mode':'world','times_s':times,'points_m':[v['target'] for v in expanded]},
                        'lens':{'times_s':[0],'values_mm':[frames[0]['lens_mm']]}}
            camera_motion=build({'shot':{'duration_s':duration},'parameters':parameters})
            trajectory=sample_motion(camera_motion,24,spec['id'],{'projection_type':'PERSP','sensor_fit':'HORIZONTAL',
                       'sensor_width_mm':36,'clip_start':.05,'clip_end':500},start_frame=1)
            result=normalize_camera_tool_result({'schema':'camera_tool_result.v0.2','run_id':episode,'status':'success',
                   'scene_id':'forest_season','trajectory':trajectory,'provenance':[{'shot_id':spec['id'],
                   'tool_call_id':'season_photography_director','frame_range':[1,count+1],'effective_params':parameters}]})
            candidates.append({'tool_result':result});intent['shots'].append({'id':spec['id'],'duration_s':duration,'transition':'cut'})
            expected_camera+=frames
    assert len(all_rows)==len(expected_camera)==11520
    for actor,root in stage.roots.items():
        positions=[row['actors'][actor]['position'] for row in all_rows]
        angles=[row['actors'][actor]['yaw'] for row in all_rows]
        grips=[row['actors'][actor]['anchor'] for row in all_rows]
        for i in sparse_indices(positions):root.location=positions[i];root.keyframe_insert('location',frame=i+1)
        for i in sparse_indices(angles):root.rotation_euler=(0,0,angles[i]);root.keyframe_insert('rotation_euler',frame=i+1)
        for i in sparse_indices(grips):stage.grips[actor].location=grips[i];stage.grips[actor].keyframe_insert('location',frame=i+1)
    positions=[row['props']['box']['position'] for row in all_rows]
    for i in sparse_indices(positions):stage.box.location=positions[i];stage.box.keyframe_insert('location',frame=i+1)
    for obj in list(stage.roots.values())+list(stage.grips.values())+[stage.box]:
        for layer in obj.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:key.interpolation='LINEAR'
    joined,boundaries=compose(candidates,intent)
    camera_file=output/f'{episode}_camera_tool_result.json';camera_file.write_text(json.dumps(joined,separators=(',',':')))
    target=output/f'{episode}.blend'
    import_camera_tool_result(str(camera_file),str(target))
    s=bpy.context.scene;maximum_root=maximum_grip=maximum_camera=maximum_axis=maximum_actor_axis=0.
    for index,(row,expected) in enumerate(zip(all_rows,expected_camera)):
        s.frame_set(index+1);deps=bpy.context.evaluated_depsgraph_get()
        for actor,value in row['actors'].items():
            maximum_root=max(maximum_root,math.dist(stage.roots[actor].evaluated_get(deps).matrix_world.translation,value['position']))
            maximum_grip=max(maximum_grip,math.dist(stage.grips[actor].evaluated_get(deps).matrix_world.translation,value['anchor']))
            actual_axis=stage.roots[actor].evaluated_get(deps).matrix_world.to_quaternion().normalized()
            wanted_axis=Quaternion((0,0,1),value['yaw']).normalized()
            maximum_actor_axis=max(maximum_actor_axis,quaternion_angle_error(tuple(actual_axis),tuple(wanted_axis)))
        maximum_root=max(maximum_root,math.dist(stage.box.evaluated_get(deps).matrix_world.translation,row['props']['box']['position']))
        camera=s.camera.evaluated_get(deps);maximum_camera=max(maximum_camera,math.dist(camera.matrix_world.translation,expected['position']))
        quaternion=(Vector(expected['target'])-Vector(expected['position'])).to_track_quat('-Z','Y')
        maximum_axis=max(maximum_axis,quaternion_angle_error(tuple(camera.matrix_world.to_quaternion()),tuple(quaternion)))
        if index%2400==0:print('BAKE_READBACK',episode,index+1,maximum_root,maximum_camera,flush=True)
    assert maximum_root<1e-5 and maximum_grip<1e-5 and maximum_camera<1e-5 and maximum_axis<.001 and maximum_actor_axis<.001,(maximum_root,maximum_grip,maximum_camera,maximum_axis,maximum_actor_axis)
    report={'episode':episode,'frames':11520,'fps':s.render.fps,'duration_s':480,'editable_blend':str(target),
            'max_actor_prop_error':maximum_root,'max_grip_error':maximum_grip,'max_camera_error':maximum_camera,
            'max_camera_axis_error_rad':maximum_axis,'blend_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            'max_actor_axis_error_rad':maximum_actor_axis,
            'camera_engine':'existing expert_route, sample_motion, sequence.compose, trajectory_importer',
            'native_finalize':'not_run','scope':'All encoded frames fcurve readback; body/visibility checked separately before rendering'}
    (output/f'{episode}_bake_checks.json').write_text(json.dumps(report,indent=2))
    print('EPISODE_BLEND_VERIFIED',episode,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--prior-dir',required=True);parser.add_argument('--episode',required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);bake(args.output,args.prior_dir,args.episode)
