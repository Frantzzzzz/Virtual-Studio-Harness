import os,sys,json,hashlib,subprocess,time
from paths import OUT,CONFIG
P=OUT/'project';role=sys.argv[1];prefix=role if len(sys.argv)<3 else role+'_'+sys.argv[2]
prompt=(P/(prefix+'_prompt.txt')).read_bytes()
schema=P/(prefix+'_schema.json') if (P/(prefix+'_schema.json')).exists() else P/('action_plan.schema.json' if role=='action' else 'camera_plan.schema.json')
output=P/(prefix+'_plan.json');folder=OUT/'jobs'/prefix;folder.mkdir(parents=True,exist_ok=False)
args=[CONFIG['codex_bin'],'exec','--ignore-user-config','--json','--skip-git-repo-check','--sandbox','read-only','-C',str(P),
      '-c','model='+CONFIG['model'],'-c','model_reasoning_effort='+CONFIG['reasoning_effort'],'-c','features.multi_agent=false',
      '-c','sandbox_workspace_write.network_access=false','--output-schema',str(schema),'--output-last-message',str(output),
      '--image',str(P/'shared_map.png'),'--image',str(P/'shared_views.jpg'),'-']
if role=='camera' and (P/'motion_observations.jpg').exists():args[-1:-1]=['--image',str(P/'motion_observations.jpg')]
if (P/(prefix+'_evidence.jpg')).exists():args[-1:-1]=['--image',str(P/(prefix+'_evidence.jpg'))]
(folder/'prompt.txt').write_bytes(prompt);(folder/'command.json').write_text(json.dumps(args,indent=2))
env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','USER','LOGNAME','SHELL','TMPDIR','LANG','LC_ALL','TERM'}}
start=time.monotonic()
with (folder/'events.jsonl').open('wb') as events,(folder/'stderr.log').open('wb') as errors:
    result=subprocess.run(args,input=prompt,env=env,stdout=events,stderr=errors,timeout=750)
events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.strip()]
usage=next((e.get('usage') for e in reversed(events) if e.get('type')=='turn.completed'),None)
receipt={'role':role,'model':CONFIG['model'],'thinking_effort':CONFIG['reasoning_effort'],'transport':'guarded Codex CLI, copied WorldOS role guidance; not native WorldOS runtime',
         'seconds':time.monotonic()-start,'exit_code':result.returncode,'usage':usage,'output':str(output),
         'shared_studio_sha256':hashlib.sha256((P/'shared_studio.json').read_bytes()).hexdigest(),
         'shared_image_sha256':{name:hashlib.sha256((P/name).read_bytes()).hexdigest() for name in ['shared_map.png','shared_views.jpg']}}
(folder/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False),flush=True)
assert result.returncode==0 and output.is_file(),(folder/'stderr.log').read_text()[-3000:]
