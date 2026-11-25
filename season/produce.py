"""Sequential Blender production with bounded photography repair and checkpoints."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from season.model_job import run_json
from season.direct_camera import validate_camera
from season.encode import encode_episode
from studio_config import load_config


def produce(output, prior_dir, start_episode=1, end_episode=5):
    output,prior_dir=Path(output),Path(prior_dir)
    config=load_config()
    sys.path.insert(0,str(config['camera_harness']))
    from camera_agent.harness.runtime.blender_process import blender_process_slot
    series=json.loads((output/'series_plan.json').read_text())
    for episode in series['episodes'][start_episode-1:end_episode]:
        ep=episode['id'];plan_path=output/f'{ep}_camera_plan.json'
        while not plan_path.exists():
            if (output/'camera_failed.json').exists():raise RuntimeError('Camera planning failed')
            time.sleep(5)
        success=False
        for revision in range(5):
            directory=output/'production'/ep/f'v{revision+1}';directory.mkdir(parents=True,exist_ok=True)
            with blender_process_slot(time.monotonic()+3600,lock_path=str(config['blender_lock'])) as lease:
                started=time.monotonic()
                args=[config['blender_bin'],'-b','--factory-startup','--disable-autoexec','-t','4','--python-exit-code','1',
                      '--python',str(Path(__file__).with_name('blender_stage.py')),'--','--output',str(output),
                      '--prior-dir',str(prior_dir),'--episode',ep]
                with (directory/'blender.log').open('w') as log:
                    process=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=lease.execution_timeout(3500))
                (directory/'receipt.json').write_text(json.dumps({'exit_code':process.returncode,'seconds':time.monotonic()-started,
                                                              'queue_seconds':lease.queue_seconds},indent=2))
            if process.returncode==0:
                success=True;break
            check_path=output/f'{ep}_production_checks.json'
            if not check_path.exists():raise RuntimeError(f'{ep}: Blender failed before producing checks; see {directory}')
            reports=json.loads(check_path.read_text())
            (directory/'checks.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
            if any(r['status']=='action_repair_required' for r in reports):
                raise RuntimeError(f'{ep}: actual scene geometry requires action-director feedback, not camera concealment')
            previous=json.loads(plan_path.read_text());shutil.copy2(plan_path,directory/'camera_plan_before.json')
            # Keep only failed shot details, not repeated per-frame samples or all previous model context.
            feedback=[r for r in reports if r['status']=='photography_repair_required']
            actions=json.loads((output/f'{ep}_action_plan.json').read_text())
            schema=json.loads((output/'jobs'/f'{ep}_camera_v1'/'schema.json').read_text())
            prompt='''你是本集原摄影指导。真实Blender全帧几何/可见性检查找到了下述失败。请只修正受影响的摄影设计，返回本集六场完整摄影计划；保留已通过的场次和所有剧情、动作、时长。不要调用工具。
可以调整允许的方位/俯角、镜头焦距（18–50mm）、projected_height（.25–.8）、跟拍或切点，不能挪演员、隐藏人物、删树、放宽可见性门槛或缩短动作。若失败是position_bounds，尝试更广角、更近的构图或降低俯角；若camera_clearance_or_containment，换允许方位；若动作后半出画，切开非接触段或用follow_actor。拍摄拿放/交接的镜头必须连续包含整个动作和所有参与人与box；不能把后半动作切没。
allowed_azimuths可用[-150,-90,-30,30,90,150]中的2–6个，allowed_elevations可用10/25/40。有限搜索失败不代表全局无解。明确依据反馈改数值，不能只改说明文字。机位优化是camera harness在你允许范围内寻找，仍需实际复验。
''' + json.dumps({'episode':episode,'previous_camera':previous,'locked_actions':actions,
                 'execution_feedback':feedback},ensure_ascii=False,separators=(',',':'))
            result=run_json(output,f'{ep}_camera_geometry_v{revision+1}',prompt,schema,config)
            errors=validate_camera(episode,result,actions)
            if errors:raise RuntimeError(f'Photography repair changed protected constraints: {errors}')
            plan_path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
            print('PHOTOGRAPHY_REPAIR_RETURNED',ep,revision+1,flush=True)
        if not success:raise RuntimeError(f'{ep}: bounded camera repair exhausted; evidence retained')
        encode_episode(output,ep)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--prior-dir',required=True)
    parser.add_argument('--start-episode',type=int,default=1)
    parser.add_argument('--end-episode',type=int,default=5)
    args=parser.parse_args()
    try:produce(args.output,args.prior_dir,args.start_episode,args.end_episode)
    except Exception as error:
        (Path(args.output)/'production_failed.json').write_text(json.dumps({'error':str(error)}))
        raise
