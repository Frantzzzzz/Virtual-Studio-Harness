import sys,time,subprocess,json
from paths import HERE,OUT,HARNESS,CONFIG
sys.path.insert(0,str(HARNESS))
from camera_agent.harness.runtime.blender_process import blender_process_slot
phase=sys.argv[1]
if phase not in {'prior','bake','film_check','repair_survey','walk_check','render'}:
    raise SystemExit('Unknown Blender phase')
with (OUT/(phase+'.log')).open('w') as log:
    with blender_process_slot(time.monotonic()+1800,lock_path=str(CONFIG['blender_lock'])) as lease:
        start=time.monotonic()
        result=subprocess.run([CONFIG['blender_bin'],'-b','--factory-startup','--disable-autoexec','-t','4','--python-exit-code','1','--python',str(HERE/(phase+'.py'))],stdout=log,stderr=subprocess.STDOUT,timeout=lease.execution_timeout(1750))
        receipt=dict(phase=phase,exit_code=result.returncode,seconds=time.monotonic()-start,queue_seconds=lease.queue_seconds)
        (OUT/(phase+'_receipt.json')).write_text(json.dumps(receipt,indent=2));print(receipt,flush=True)
        sys.exit(result.returncode)
