"""Export completed episodes under the same shared Blender process lock."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from studio_config import load_config


def bake_all(output,prior_dir):
    output=Path(output);config=load_config();sys.path.insert(0,str(config['camera_harness']))
    from camera_agent.harness.runtime.blender_process import blender_process_slot
    for i in range(1,6):
        ep=f'ep{i:02d}'
        while not (output/f'{ep}_video_checks.json').exists():time.sleep(5)
        if (output/f'{ep}_bake_checks.json').exists():continue
        with blender_process_slot(time.monotonic()+3600,lock_path=str(config['blender_lock'])) as lease:
            start=time.monotonic()
            with (output/f'{ep}_bake.log').open('w') as log:
                process=subprocess.run([config['blender_bin'],'-b','--factory-startup','--disable-autoexec','-t','4',
                         '--python-exit-code','1','--python',str(Path(__file__).with_name('bake_episode.py')),
                         '--','--output',str(output),'--prior-dir',str(prior_dir),'--episode',ep],
                         stdout=log,stderr=subprocess.STDOUT,timeout=lease.execution_timeout(3500))
            receipt={'episode':ep,'exit_code':process.returncode,'seconds':time.monotonic()-start,'queue_seconds':lease.queue_seconds}
            (output/f'{ep}_bake_receipt.json').write_text(json.dumps(receipt,indent=2))
            print('BAKE_RECEIPT',json.dumps(receipt),flush=True)
            if process.returncode:raise RuntimeError(f'{ep}: editable-scene export failed; inspect bake.log')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--prior-dir',required=True);a=p.parse_args()
    bake_all(a.output,a.prior_dir)
