import json,hashlib,math
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont
from paths import OUT,HERE,HARNESS,font as load_font
P=OUT/'project'
read=lambda name:json.loads((OUT/name).read_text())
checks=read('film_checks.json');walk=read('walk_checks.json');decode=read('video_decode_checks.json');assert checks['status']==walk['status']=='pass'
rows=read('motion_samples.json');actions=json.loads((P/'action_plan.json').read_text());camera=json.loads((P/'camera_plan.json').read_text());binding=read('actor_clip_manifest.json');studio=json.loads((P/'shared_studio.json').read_text())
assert hashlib.sha256(Path(binding['animated_scene']).read_bytes()).hexdigest()==binding['scene_version']
assert hashlib.sha256((P/'shared_studio.json').read_bytes()).hexdigest()==json.loads((P/'binding.json').read_text())['shared_studio_sha256']
receipts=[json.loads(p.read_text()) for p in sorted((OUT/'jobs').glob('*/receipt.json'))]
assert len({r['shared_studio_sha256'] for r in receipts})==1
assert len({json.dumps(r['shared_image_sha256'],sort_keys=True) for r in receipts})==1
usage={key:sum((r.get('usage') or {}).get(key,0) for r in receipts) for key in ['input_tokens','cached_input_tokens','output_tokens']};usage['uncached_input_tokens']=usage['input_tokens']-usage['cached_input_tokens']
time=sum(r['seconds'] for r in receipts)
measurements=read('film_frame_measurements.json');visible={}
for row in measurements:
    key=row['shot'];summary=visible.setdefault(key,{'frames':0,'minimum_ratios':{}});summary['frames']+=1
    for name,value in row['visibility']['visible_ratio'].items():summary['minimum_ratios'][name]=min(summary['minimum_ratios'].get(name,1),value if value is not None else 0)
# Frame-matched RGB check and a labelled review copy; captions describe event records, not grasp physics.
cap=cv2.VideoCapture(str(OUT/'forest_capsule_preview.mp4'));writer=cv2.VideoWriter(str(OUT/'review.pending.mp4'),cv2.VideoWriter_fourcc(*'avc1'),24,(768,496));assert writer.isOpened()
font=load_font(20);small=load_font(17)
ta,tb,tr,td=[e['t'] for e in actions['events']];owner_names={'CHAR-0001':'橙 A','CHAR-0002':'绿 B','CHAR-0003':'蓝 C'};rgb_checks=[]
for i,row in enumerate(rows):
    ok,frame=cap.read();assert ok
    png=OUT/f'film_frame_{i+1:04d}.png'
    if png.exists():
        reference=cv2.imread(str(png));difference=np.abs(frame.astype(float)-reference.astype(float));rgb_checks.append({'frame':i+1,'mean_absolute_pixel_difference':float(difference.mean()),'rmse':float(np.sqrt((difference*difference).mean()))})
    t=i/24;phase='A 接近第一张台并拿取盒子' if t<ta else 'A 持盒走向交接位置，B 会合' if t<tb else 'A 与 B 共同持有' if t<tr else 'B 接走盒子，移向第二张台' if t<td else '盒子落台，B 退开'
    canvas=Image.new('RGB',(768,496),'#111827');canvas.paste(Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)),(0,0));draw=ImageDraw.Draw(canvas)
    draw.text((12,436),f'{t:05.2f} / {actions["duration_s"]:g}s   {phase}',font=font,fill='white')
    owners=row['props']['box']['owners'];holder=' + '.join(owner_names[id] for id in owners) if owners else '无（台面）'
    draw.text((12,468),'橙 A · 绿 B · 蓝 C     持有记录：'+holder+'    胶囊占位预演',font=small,fill='#dbe4ef')
    writer.write(cv2.cvtColor(np.asarray(canvas),cv2.COLOR_RGB2BGR))
assert not cap.read()[0];cap.release();writer.release()
temporary=OUT/'review.pending.mp4';cap=cv2.VideoCapture(str(temporary));n=0;pts_error=0
while True:
    ok,image=cap.read()
    if not ok:break
    pts_error=max(pts_error,abs(cap.get(cv2.CAP_PROP_POS_MSEC)/1000-n/24));n+=1
cap.release();assert n==423 and pts_error<.002;temporary.replace(OUT/'review.mp4')
(OUT/'encoded_rgb_checks.json').write_text(json.dumps({'comparisons':rgb_checks,'scope':'Matched final encoded frames vs pre-rendered RGB keyframes; codec/sample differences recorded, not a universal image quality threshold'},indent=2)+'\n')
summary={'status':'local_capsule_module_integration_verified','native_harness_finalize':'not_run',
         'scope':{'duration_s':actions['duration_s'],'fps':24,'frames':423,'actors':3,'props':1,'shots':len(camera['shots']),'scene':'Pinned existing forest clay/LOD blend, local region only'},
         'shared_binding':json.loads((P/'binding.json').read_text()),'common_shared_input_verified_for_all_jobs':True,
         'reuse':read('reuse_evidence.json'),'motion':read('motion_compile_checks.json'),'baked_motion':read('blender_motion_checks.json'),
         'walking':walk,'filming':{key:value for key,value in checks.items() if key!='failures'},'visibility_summary':visible,
         'coordination':{'story':'Host-supplied fixed diagnostic story','action_guidance':'Independent Codex role using WorldOS role guidance, including two narrow posture repairs',
             'photography_guidance':'Independent Codex role using WorldOS role guidance, including two-shot revision/split after real visibility feedback',
             'creative_timing_owner':'Action director; 17.625s unchanged by the executor',
             'camera_revision_preserved_animated_scene_sha256':binding['scene_version'],
             'not_tested':'Autonomous three-way creative negotiation and story/action-change impact propagation'},
         'role_cost':{'jobs_including_repairs':len(receipts),'execution_seconds':time,**usage,
                     'scope':'Model-job logs only; excludes this chat, one-off adapter development, historical evidence curation and host reasoning. Not a controlled comparison against full WorldOS.'},
         'video':decode,'annotated_review':{'path':str(OUT/'review.mp4'),'frames_decoded':n,'max_timestamp_error_s':pts_error,'captions':'Holding records from the action event timeline; not physical grasp proof'},
         'limitations':['Kitchen capsules only: no body bend/arms/gait/fingers; bend_rad affects hidden grip reach calculation only',
              'Local region and anchor candidates supplied by host then measured; no automatic whole-forest semantic stage discovery',
              'Walking proxy excludes GroundPlants category, which itself is a heuristic spatial grouping and may contain non-vegetation; no universal physical walkability certification',
              'Camera image-ray checks use full current forest proxy geometry; original high-detail foliage/material scene not tested',
              'Distant background cells omitted for diagnostic RGB/video; background/lighting may differ from full-scene rendering',
              'One scene only, not 8min or multi-episode; no Seedance/Wan; no full native WorldOS application run or native camera-harness finalize']}
(OUT/'report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
report=f'''Forest 局部共享影棚＋厨房胶囊人：实际执行记录

结论：现有camera harness的场景理解/几何观察能力可以复用。本次沿用局部空地，补充10个站位候选、39条已测连接及14个勘景视点，让上游动作指导和摄影指导共享同一版本，实际拍出17.625秒、24FPS、423帧、7镜的厨房胶囊人预演。
这是一场模块集成小样，非完整WorldOS工作流，也未运行原生camera harness finalize，不能当作长剧或生产终验。

复用了什么
- SceneIndex的对象身份、搜索与空间范围；原森林34552几何实例→405空间块的既有资产与索引，不重新分类/建模。
- trajectory_verifier的实际网格BVH、闭合体内外判定及线段净空；observation_geometry同射线遮挡；view_search有限候选视点与可见性排序。
- 用户给出的历史inspect RGB/深度勘景，核对相同场景哈希后复制为带出处的环境事实；不将空间块误认成独立树。
- 现有standin_samples与WorldOS sample/hand_anchor；相机复用expert_route、sample_motion、sequence.compose和trajectory_importer。
- 厨房pin()的身体/头/白色朝向点/Wave Texture条纹几何与材质。橙A、绿B、蓝C，无腿、手臂、骨架或蒙皮；根节点线性移动/转向，盒子跟随不可见中心挂点。

创作与执行的责任
- 剧情、初末状态由宿主固定。动作指导自行选择站位、路线、时刻、转向和节奏，给出17.625秒，没有统一六秒镜长，也没有视频倍速。
- 计算器对两处中心挂点适配误差返回定量反馈，动作指导分别选择了A取物0.42、B落台0.45的前俯参数；只用于隐形挂点可达性，胶囊身体没有前俯动画。原有动作时刻/路径不变。
- 摄影指导读取相同base包及烘焙后追加的动作观察，先设计6镜。全帧检查发现第2镜7帧、第3镜44帧黄盒被A身体挡住，旧结果保留在camera_revision1。
- 宿主补测有限替代视点并反馈，摄影指导自己选择反侧机位，在6.5秒转身处增切一镜，最终7镜。人物/道具动画文件哈希未变，只改摄影。
- 角色沟通目前由共享文件和宿主反馈撮合。三方自主创作协商、修改剧情或动作后自动传播连锁影响尚未实现/验证。

检查证据
- 实际烘焙423帧，根节点、朝向、隐形挂点和道具位置回读；最大位置误差约{summary['baked_motion']['max_position_error']:.3g}个场景单位。
- 最终摄影全423帧相机净空、静态环境线段与必需头部/盒子采样可见性检查通过。可见性门槛是本次工程检查的>=0.5且足够采样，不是通用审美/语义认证。
- 实际根点相对Terrain误差范围{walk['terrain_root_error_range']}；声明的静态障碍类别和竖直球体代理的移动线段复核通过。GroundPlants不作为身体硬障碍，不能宣称全场景物理无碰撞。
- 上一轮灰屏机位被现有harness判为inside_closed_evaluated_mesh，空间块Trees_cell_+01_+01；最终不再使用该机位。
- 原始forest blend和锁定的motion.blend文件哈希均不变；相机和动作时钟统一。两个角色所有工单的共同场景包、地图、勘景图哈希完全一致。
- 原始预演与带标签审阅版均完整解码423帧；最终编码关键帧与诊断RGB的差异记录在encoded_rgb_checks.json。

成本
- 5个指导工单（初始动作、两次姿态修正、初始摄影、摄影修正）累计{time:.1f}秒（约{time/60:.2f}分钟）。
- 累计输入{usage['input_tokens']} token，其中缓存{usage['cached_input_tokens']}、非缓存{usage['uncached_input_tokens']}；输出{usage['output_tokens']}。
- 以上仅工单统计，不含本会话和一次性适配代码开发/宿主整理。与旧36秒可见手臂完整WorldOS链的时长、表示和流程均不同，不构成公平性能对照。
- 机器阶段耗时见各*_receipt.json，失败测量/首版摄影保留；最终render耗时不代表全部端到端耗时。

产物
- review.mp4：带时间/持有记录的审阅版，字幕来自事件表，不证明真实抓握。
- forest_capsule_preview.mp4：无字幕的实际森林预演。
- motion.blend：包含全部森林几何、角色和道具的锁定动画副本。
- candidate_scene.blend：在该动画上导入相机的完整几何副本。为预演提速，只在渲染时裁去远处背景，名单在film_render_scope.json。
- project/shared_studio.json、navigation_details.json、camera_catalog.json：共享局部先验、路线与候选视点，场景包未接成默认公共工具。
- project/action_plan.json、project/camera_plan.json、jobs/*：上游计划、反馈和模型时间/token回执。

边界：仅当前白模/LOD森林的一场。站位候选来自宿主选定区域并经测量；不是自动理解整片森林的通用系统。没有真实人体表演/抓握、光学透明材质认证、8分钟单集或跨集状态衔接，也未接Seedance/Wan。
'''
(OUT/'REPORT.txt').write_text(report)
(OUT/'STATUS.json').write_text(json.dumps({'status':summary['status'],'report':str(OUT/'REPORT.txt'),'video':str(OUT/'review.mp4'),'native_finalize':'not_run'},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':summary['status'],'duration_s':actions['duration_s'],'shots':len(camera['shots']),'role_seconds':time,'usage':usage,'review':str(OUT/'review.mp4')},ensure_ascii=False))
