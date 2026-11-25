import json
from paths import OUT,font as load_font
from PIL import Image,ImageDraw,ImageFont
P=OUT/'project';observations=json.loads((OUT/'motion_view_observations.json').read_text())
compact=[{'id':r['id'],'station_id':r['station_id'],'mode':r['mode'],'state':r['state'],'minimum_sampled_visibility':r['minimum_sampled_visibility'],
          'eligible':r['eligible_for_same_pose_samples'],'sample_times':[x['t'] for x in r['samples']]} for r in observations]
(P/'motion_view_options.json').write_text(json.dumps(compact,ensure_ascii=False,indent=2)+'\n')
font=load_font(20);sheet=Image.new('RGB',(1280,3*390),'#111827');draw=ImageDraw.Draw(sheet)
for i,state in enumerate(['establish','pickup','handover','carry','drop']):
    path=OUT/('actual_'+state+'.png')
    if path.exists():sheet.paste(Image.open(path).convert('RGB'),((i%2)*640,(i//2)*390+30))
    draw.text(((i%2)*640+8,(i//2)*390+5),'Actual new motion: '+state,font=font,fill='white')
sheet.save(P/'motion_observations.jpg',quality=90)
string={'type':'string'};number={'type':'number'}
def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
shot=obj({'id':string,'start_s':number,'end_s':number,'state':{'type':'string','enum':['establish','pickup','handover','carry','drop']},
          'station_id':string,'mode':{'type':'string','enum':['static','track_subject','push_in']},
          'follow_actor':{'type':['string','null'],'enum':['CHAR-0001','CHAR-0002','CHAR-0003',None]},
          'push_distance':number,'fov_y_deg':{'type':['number','null']},'required_actors':{'type':'array','items':{'type':'string','enum':['CHAR-0001','CHAR-0002','CHAR-0003']}},
          'require_box':{'type':'boolean'},'visual_goal':string,'camera_description':string})
schema=obj({'design_rationale':string,'shots':{'type':'array','items':shot,'minItems':4,'maxItems':8}})
(P/'camera_plan.schema.json').write_text(json.dumps(schema,indent=2)+'\n')
prompt='''你是本场上游摄影指导，本轮兼任分镜。沿用WorldOS camera-movement专业规范，但执行的是一份受限Codex工单，不启动完整WorldOS工作流。你的职责是决定拍法、切点、景别和摄影节奏；动作与剧情已锁定，执行器不替你创作。
必读scene_story.txt、binding.json、shared_studio.json、motion_context.json、motion_view_options.json、roles/photography_director.md。实际查看初始共享图shared_map/shared_views，以及新的motion_observations.jpg。两个指导的基础场景包完全相同；motion_context和新图是动作工位产生后实测的追加事实。不要读整个逐帧数组、源码、其他工位规范或旧试验计划。只可读本项目，不安装、不联网、不派生、不运行Blender或写执行器。
影片全长严格等于motion_context.duration_s，24fps，镜头时间须在1/24秒格点；首镜start=0，逐镜无缝覆盖直到duration_s。你决定4–8个镜头及切点，不能机械等分时长，不能修改动作或跳时间。完整拿取、共同持有、A松手、B带离和放下应拍清楚。
从shared_studio.camera_views选择station_id，它是上游可选的、真实几何测量的摄影站位，不是强制拍法。motion_view_options列出了在这次真实动作若干姿态下的可见性重测；优先eligible=true，全部仍需最终逐帧检查。mode=static保持站位与关注点；track_subject按你指定角色的根节点平移相机及关注点、维持站位的相对偏移；push_in沿站位到关注点方向推进push_distance，关注点固定，不复合运动。非push_in时push_distance=0；非track时follow_actor=null。track只对carry阶段提供了实测候选，follow_actor应为B。fov_y_deg=null沿用勘景站位，需改景别可以显式选择数值，不能无依据变更来掩盖遮挡。
station采用WorldOS Y-up坐标和垂直FOV；不是Blender XY平面，请不要自行猜坐标。若track选B，程序以camera_catalog的carry校准姿态计算相对B的偏移，再跟随这次B的位置；你决定使用该拍法，程序只计算轨迹。摄影范围是厨房胶囊人，不存在手臂；拿放与交接以黄色盒子和中心挂点表示，不要求人体抓握。
首镜交代三名角色，required_actors三人；拿取镜至少A+盒；交接镜必须A/B+盒，B加入共同持有到A释放之后的过程不能被切点割断；携盒镜至少B+盒；落台与收手退步至少B+盒且最后静置可辨。其他人可以画外，但不允许从场景中删除。
按camera_plan.schema.json只返回JSON。每镜写清visual_goal和具体camera_description。根据实测图选择拍法，不是填表凑出固定/推/跟等种类；静态镜头也可以。你可做常规可逆局部修正，任务已获授权，不需要二次批准。不得声称已经正式终验或签字。
'''.replace('\n+','\n')
(P/'camera_prompt.txt').write_text(prompt)
print('CAMERA_PACKET_READY',len(compact))
