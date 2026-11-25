"""Reuse calibrated immutable forest observations supplied by the user."""
import json,hashlib,shutil
from paths import OUT,CONFIG
ROOT=CONFIG['history_root']
if ROOT is None:
    (OUT/'historical_observations.json').write_text(json.dumps({'observations':[],'original_agent_actions':{},'scope':'No optional historical observations configured'},indent=2)+'\n')
    print('No historical observations configured')
    raise SystemExit(0)
records=[]
for p in (ROOT/'backend').glob('*/request.json'):
    request=json.loads(p.read_text());view=request.get('view') or {}
    if view.get('position') not in [[26.,19.,2.],[26.,23.,2.]]:continue
    assert request['scene_version']==CONFIG['source_sha256']
    result=json.loads((p.parent/'result.json').read_text());media=[]
    for m in result['media']:
        original=__import__('pathlib').Path(m['path']);dest=OUT/'historical_observations'/f'{int(view["position"][1])}_{original.name}';dest.parent.mkdir(exist_ok=True)
        shutil.copy2(original,dest);entry=dict(m,original_path=str(original),path=str(dest),actual_sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
        calibration=m.get('calibration') or {}
        if calibration.get('image_sha256'):assert entry['actual_sha256']==calibration['image_sha256']
        media.append(entry)
    records.append({'original_request':str(p),'request':request,'media':media,'scope':'Original forest environment only, no actors or current props; exact pinned scene version'})
responses={n:(ROOT/'model'/n/'response.txt').read_text() for n in ['0002','0011','0012']}
(OUT/'historical_observations.json').write_text(json.dumps({'observations':records,'original_agent_actions':responses,'spatial_groups_are_not_individual_trees':True},ensure_ascii=False,indent=2)+'\n')
print('reused historical observations',len(records))
