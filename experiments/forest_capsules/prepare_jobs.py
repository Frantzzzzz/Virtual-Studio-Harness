import json,hashlib,shutil
from pathlib import Path
from paths import OUT,HERE,WORLDOS,font as load_font
from PIL import Image,ImageDraw,ImageFont

P=OUT/'project';P.mkdir(exist_ok=True)
prior=json.loads((OUT/'shared_studio.json').read_text())
shutil.copy2(OUT/'shared_studio.json',P/'shared_studio.json')
shutil.copy2(OUT/'navigation_details.json',P/'navigation_details.json')
shutil.copy2(OUT/'historical_observations.json',P/'historical_observations.json')
binding={'shared_studio_sha256':hashlib.sha256((P/'shared_studio.json').read_bytes()).hexdigest(),'source_blend_sha256':prior['source_sha256'],'fps':24}
(P/'binding.json').write_text(json.dumps(binding,indent=2)+'\n')
font=load_font(18)
states=['establish','pickup','handover','carry','drop'];sheet=Image.new('RGB',(1280,5*390),'#111827');draw=ImageDraw.Draw(sheet)
for row,state in enumerate(states):
    views=[v for v in prior['camera_views'] if v['calibration_state']==state][:2]
    for col,view in enumerate(views):
        im=Image.open(view['image']).convert('RGB').resize((640,360));sheet.paste(im,(640*col,390*row+30));draw.text((640*col+8,390*row+5),view['id'],font=font,fill='white')
sheet.save(P/'shared_views.jpg',quality=90)
plan=Image.new('RGB',(1000,1000),'#16202c');d=ImageDraw.Draw(plan)
def xy(x,z):return (500+x*55,500+z*55)
nav=json.loads((OUT/'navigation_details.json').read_text())
for cell in nav['grid']:
    x,z=cell['position'][0],cell['position'][2];px,py=xy(x,z);d.rectangle((px-12,py-12,px+12,py+12),fill='#3f745d' if cell['clear'] else '#864b4b')
for name,a in prior['anchors'].items():
    px,py=xy(a['position'][0],a['position'][2]);d.ellipse((px-5,py-5,px+5,py+5),fill='white');d.text((px+7,py),name,font=font,fill='white')
for v in prior['camera_views']:
    px,py=xy(v['position'][0],v['position'][2]);d.ellipse((px-4,py-4,px+4,py+4),fill='#f7c343');d.text((px+5,py+5),v['id'],font=load_font(12),fill='#f7c343')
d.text((20,15),'Sampled local studio. X right; -Z up; 1 unit assumed 1m.',font=font,fill='white')
d.text((20,45),'Green: standing proxy clear. Red: rejected. Yellow: measured camera proposal.',font=font,fill='white')
d.text((20,950),'Walking grid is not semantic/visual approval; all new motions must be checked.',font=font,fill='white')
plan.save(P/'shared_map.png')
story='''场景：固定森林影棚中的证物交接。无对白、无新增角色。
初态：橙色A在west_entry，绿色B在east_wait，蓝色C在observer。黄色盒子放在pickup_box位置，无人持有。
剧情：A走近第一张台，拿起盒子；A、B在交接区会合，停稳面对面后交接，有短暂共同持有，A松手，B独自携盒走到第二张台，放下、收手、退半步；C全程在场观察。
终态：盒子稳定放在drop_box位置；A空手留在交接区；B空手退开；C仍在场。
沿用厨房胶囊人，根节点移动与转向；无腿、手臂、骨架或手指，道具跟随隐形中心交互挂点。无Seedance。
这次没有预先均分的六秒镜长。动作指导决定走位、姿态、动作节奏与全部关键时刻；摄影指导决定镜头划分和拍法，双方使用同一个共享场景包。执行程序不得自行改变时长/节奏或隐藏冲突。
目标是紧凑清楚的动作预演，不用等待填满时长。允许两人并行移动。必须让拿取、共同持有、松手带离和最终落台可辨。
'''
(P/'scene_story.txt').write_text(story)
roles=P/'roles';roles.mkdir(exist_ok=True)
for name,source in [('action_director','whitebox-staging'),('photography_director','camera-movement')]:
    src=WORLDOS/f'agents/07-directing/{source}/SOUL.md';shutil.copy2(src,roles/(name+'.md'))
# A compact role-specific job uses original role guidance, without starting the full WorldOS workflow.
item=lambda props,req=None:{'type':'object','properties':props,'required':req or list(props),'additionalProperties':False}
num={'type':'number'};text={'type':'string'}
rootkey=item({'t':num,'node':text})
posekey=item({'t':num,'yaw_deg':num,'pose':{'type':'string','enum':['rest','carry','pickup_contact','share_contact','drop_contact']}})
actor=item({'root_keys':{'type':'array','items':rootkey,'minItems':2},'pose_keys':{'type':'array','items':posekey,'minItems':2}})
event=item({'t':num,'kind':{'type':'string','enum':['hold','release']},'actor':{'type':'string','enum':list(prior['actor_sizes'])}})
beat=item({'id':text,'start_s':num,'end_s':num,'description':text})
action_schema=item({'duration_s':{'type':'number','minimum':8,'maximum':45},'design_rationale':text,
    'actors':item({id:actor for id in prior['actor_sizes']}),'events':{'type':'array','items':event,'minItems':4,'maxItems':4},
    'beats':{'type':'array','items':beat,'minItems':4,'maxItems':10}})
(P/'action_plan.schema.json').write_text(json.dumps(action_schema,indent=2))
prompt='''你是本场的上游动作指导，负责创作决定，不是执行器。本轮采用WorldOS whitebox-staging的专业职责，但运行方式是独立、受限Codex工单，不启动WorldOS完整工作流。以本工单的输出边界为准：只做动作，不生成摄影方案，不重新写整集。
先读 scene_story.txt、binding.json、shared_studio.json、roles/action_director.md，并实际查看附件 shared_map.png 和 shared_views.jpg。两位指导将共享相同的binding和场景信息。不要读取上一次试验的计划、简历、私人目录或凭据；不要安装、联网、派生Agent或运行Blender。
输出符合 action_plan.schema.json 的JSON（直接作为最终回复）。这是动作指导自己的设计，不抄上一版时间表：你决定每个动作的时刻、先后/并行、站位、转向与停顿。所有时间须落在1/24秒格点，duration_s也一样。0和duration_s必须被每位角色的root_keys与pose_keys覆盖。A/B不得瞬移，C全程在场。
root_keys里的node使用实测anchors。两个不同node之间必须存在shared_studio.routes所列直达路径，可反向；没有直达边就插入中间node（例如pickup_stand经west_bypass到handover_A）。程序只沿你选择的路径按你的时间移动，不改节奏。姿态key中的pose使用已有五个模板：rest为空手中心挂点；carry持盒腹前；pickup_contact前俯接触pickup_box；share_contact接触shared_box；drop_contact前俯接触drop_box。yaw_deg是WorldOS朝向：0朝+Z，90朝+X，-90朝-X，180朝-Z。手部/挂点计算由程序执行。
道具只有一个，初始无人持有。events严格四个：A hold（挂点已在pickup_box），B hold（A、B均到shared_box，成为共同持有），A release（B已握稳），B release（挂点在drop_box）。同一时刻需要保持姿态时，请明确安排相邻姿态key，避免从拾取接触瞬间开始就转向、或在release之前缩回挂点。取起后先离台、收至carry再走；共同持有期间双方根节点与share_contact姿态固定；A放手后才能收手。B落台后再rest收手/退开。
实际观看勘景图：起步、会合、携盒移动可以并行安排，但必须留足可见的拿取/共同持有/松手/落台过程。最后至少0.5秒盒子静置。不要为了凑整时长无理由等下一镜。pose仅控制隐形挂点和计算姿态，不承诺真人表演；胶囊人只显示根节点移动/转向。
这是创作工单，常规可逆修正已获授权，不需要用户二次批准。最多读取本项目必要材料；不要阅读其他角色完整工作流或新增规范。最后只返回JSON，不写说明文件或自建执行器。
'''
(P/'action_prompt.txt').write_text(prompt)
(P/'packet_manifest.json').write_text(json.dumps({'binding':binding,'roles_transport':'Two scoped authenticated Codex CLI jobs using copied WorldOS role guidance; not a native WorldOS application run',
 'host_supplied':['fixed story','shared measured studio','interface and reusable posture templates'],'upper_roles_decide':['blocking/timing/orientation','shot structure/movement/attention/optics'],
 'shared_inputs':['shared_studio.json','shared_map.png','shared_views.jpg','scene_story.txt']},ensure_ascii=False,indent=2)+'\n')
print('PROJECT_READY',len((P/'shared_studio.json').read_text()),len(prior['camera_views']))
