"""Independently reopen saved blends and verify all encoded frames, without rewriting them."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import argparse
import hashlib
import json
import math
import subprocess
import time
from studio_config import load_config
from season.motion import quaternion_angle_error


def verify(output):
    import bpy
    from mathutils import Quaternion
    output=Path(output);series=json.loads((output/'series_plan.json').read_text());reports=[]
    for episode in series['episodes']:
        ep=episode['id'];file=output/f'{ep}.blend';before=hashlib.sha256(file.read_bytes()).hexdigest()
        bpy.ops.wm.open_mainfile(filepath=str(file),load_ui=False,use_scripts=False)
        scene=bpy.context.scene;motion=[]
        for spec in episode['scenes']:
            motion+=json.loads((output/'scenes'/spec['id']/'motion.json').read_text())['samples']
        tool=json.loads((output/f'{ep}_camera_tool_result.json').read_text());cameras=[]
        for shot in tool['trajectory']['shots']:
            cameras += [dict(frame,camera_name=shot['camera_name']) for frame in shot['frames']]
        assert len(motion)==len(cameras)==11520 and scene.render.fps==24
        maximum_position=maximum_angle=maximum_lens=0.;started=time.monotonic()
        for index,(row,expected) in enumerate(zip(motion,cameras)):
            scene.frame_set(index+1);deps=bpy.context.evaluated_depsgraph_get()
            assert expected['frame']==index+1 and scene.camera.name==expected['camera_name']
            for actor,value in row['actors'].items():
                root=bpy.data.objects['PREVIS_'+actor].evaluated_get(deps)
                grip=bpy.data.objects['GRIP_'+actor].evaluated_get(deps)
                maximum_position=max(maximum_position, math.dist(root.matrix_world.translation,value['position']),
                                     math.dist(grip.matrix_world.translation,value['anchor']))
                maximum_angle=max(maximum_angle,quaternion_angle_error(tuple(root.matrix_world.to_quaternion()),
                                   tuple(Quaternion((0,0,1),value['yaw']))))
            box=bpy.data.objects['PROP_box'].evaluated_get(deps)
            camera=scene.camera.evaluated_get(deps)
            maximum_position=max(maximum_position,math.dist(box.matrix_world.translation,row['props']['box']['position']),
                                 math.dist(camera.matrix_world.translation,expected['location']))
            maximum_angle=max(maximum_angle,quaternion_angle_error(tuple(camera.matrix_world.to_quaternion()),expected['rotation_quaternion']))
            maximum_lens=max(maximum_lens,abs(camera.data.lens-expected['lens_mm']))
        assert maximum_position<1e-5 and maximum_angle<.001 and maximum_lens<1e-4
        assert hashlib.sha256(file.read_bytes()).hexdigest()==before
        reports.append({'episode':ep,'reopened_saved_blend':True,'frames':11520,'max_position_error':maximum_position,
                        'max_angle_error_rad':maximum_angle,'max_lens_error_mm':maximum_lens,'seconds':time.monotonic()-started,
                        'file_unchanged':True,'sha256':before})
        print('SAVED_BLEND_VERIFIED',ep,json.dumps(reports[-1]),flush=True)
    (output/'saved_reload_checks.json').write_text(json.dumps({'status':'pass','total_frames':57600,'episodes':reports},indent=2))


def host(output,wait):
    output=Path(output)
    while any(not (output/f'ep{i:02d}_bake_checks.json').exists() for i in range(1,6)):
        if not wait:raise ValueError('Editable scenes not all complete')
        time.sleep(5)
    config=load_config();sys.path.insert(0,str(config['camera_harness']))
    from camera_agent.harness.runtime.blender_process import blender_process_slot
    with blender_process_slot(time.monotonic()+3600,lock_path=str(config['blender_lock'])) as lease:
        with (output/'saved_reload_verify.log').open('w') as log:
            process=subprocess.run([config['blender_bin'],'-b','--factory-startup','--disable-autoexec','-t','4',
                     '--python-exit-code','1','--python',str(Path(__file__).resolve()),'--','--worker','--output',str(output)],
                     stdout=log,stderr=subprocess.STDOUT,timeout=lease.execution_timeout(3500))
        if process.returncode:raise RuntimeError('Saved-scene verification failed; see saved_reload_verify.log')
        print('ALL_SAVED_BLENDS_VERIFIED',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--wait',action='store_true');parser.add_argument('--worker',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
    if args.worker:verify(args.output)
    else:host(args.output,args.wait)
