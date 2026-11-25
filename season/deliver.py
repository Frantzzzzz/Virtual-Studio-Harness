"""Verify the whole season and write a local review page, script and evidence."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import time
from season.continuity import initial_state, check_scene_script


def deliver(output, wait=False):
    output=Path(output)
    required=[output/f'ep{i:02d}_{kind}_checks.json' for i in range(1,6) for kind in ('video','bake')]
    required.append(output/'saved_reload_checks.json')
    while any(not p.exists() for p in required):
        if not wait:raise ValueError('Season is not complete: video or editable blend checks missing')
        time.sleep(5)
    series=json.loads((output/'series_plan.json').read_text())
    binding=json.loads((output/'stage_binding.json').read_text())
    camera_min,camera_max=binding['verified_camera_volume']
    story_state=initial_state(series);physical=None;previous_endpoint=None
    continuity=[];episodes=[];all_keys=set();dialogue_texts=[];text=[f'# {series["title"]}',series['premise'],'']
    for episode in series['episodes']:
        ep=episode['id'];script=json.loads((output/f'{ep}_script.json').read_text())
        camera=json.loads((output/f'{ep}_camera_plan.json').read_text())
        video=json.loads((output/f'{ep}_video_checks.json').read_text())
        bake=json.loads((output/f'{ep}_bake_checks.json').read_text())
        assert video['frames_decoded']==11520 and video['duration_s']==480 and bake['frames']==11520
        text += [f'## {ep.upper()} · {episode["title"]} · 08:00',episode['logline'],'']
        scene_reports=[];offset=0
        for outline,screenplay,photography in zip(episode['scenes'],script['scenes'],camera['scenes']):
            scene=outline['id'];directory=output/'scenes'/scene
            motion=json.loads((directory/'motion.json').read_text())
            frame_manifest=json.loads((directory/'frames.json').read_text())
            body=json.loads((directory/'body_checks.json').read_text());checks=json.loads((directory/'camera_checks.json').read_text())
            solved=json.loads((directory/'solved_camera.json').read_text())
            assert body['status']==checks['status']=='pass',scene
            assert [s['shot'] for s in solved]==photography['shots'],'Stale camera solution: '+scene
            # Older checkpoints predate the explicit ROI guard: audit their
            # accepted actual camera samples too, rather than trusting a label.
            assert frame_manifest['source_scene_sha256']==binding['source_scene_sha256']
            for solution in solved:
                assert all(camera_min[i]+.15<=frame['position'][i]<=camera_max[i]-.15
                           for frame in solution['frames'] for i in range(3)),('Camera left verified local volume',scene)
            assert frame_manifest['frame_count']==outline['duration_s']*24
            assert len(frame_manifest['frame_keys'])==frame_manifest['frame_count']
            if physical is not None:
                assert physical==motion['entry'],('Physical state reset',scene)
                first=motion['samples'][0]
                maximum=max(abs(a-b) for actor in 'ABC' for channel in ('position','anchor')
                            for a,b in zip(previous_endpoint['actors'][actor][channel],first['actors'][actor][channel]))
                maximum=max(maximum,max(abs(a-b) for a,b in zip(previous_endpoint['props']['box']['position'],first['props']['box']['position'])))
                assert maximum<1e-8,('Boundary transform jump',scene,maximum)
                continuity.append({'from':story_state['last_scene'],'to':scene,'maximum_endpoint_error':maximum,
                                   'cross_episode':not story_state['last_scene'].startswith(ep)})
            story_state,errors,stats=check_scene_script(outline,screenplay,story_state,series)
            assert not errors,(scene,errors)
            physical=motion['exit'];previous_endpoint=motion['endpoint']
            all_keys.update(frame_manifest['frame_keys'])
            scene_reports.append({'scene':scene,'duration_s':outline['duration_s'],'shots':len(photography['shots']),
                                  'unique_pixel_states':frame_manifest['unique_pixel_states'],
                                  'dialogue_characters':stats['dialogue_characters'],'speech_seconds':stats['speech_seconds'],
                                  'motion':motion['diagnostics'],'body':body,
                                  'camera_check_frames':checks['frames_checked_including_rejected']})
            text += [f'### {scene} · {offset:.1f}–{offset+outline["duration_s"]:.1f}s',
                     f'剧情：{screenplay["summary"]}',f'盒子：{motion["entry"]["box"]} → {motion["exit"]["box"]}','']
            for line in screenplay['dialogue']:
                dialogue_texts.append(line['text'])
                name=next(c['name'] for c in series['characters'] if c['id']==line['speaker'])
                text.append(f'- [{line["start_s"]:g}–{line["end_s"]:g}s] **{name}**：{line["text"]}')
            text += ['','拍摄：']
            for shot in photography['shots']:
                text.append(f'- {shot["start_s"]:g}–{shot["end_s"]:g}s · {shot["lens_mm"]:g}mm · {shot["motion"]} · {shot["intent"]}')
            text.append('');offset+=outline['duration_s']
        assert offset==480
        saved=json.loads((output/f'{ep}_story_state.json').read_text())
        assert all(story_state[k]==saved[k] for k in ('public_facts','knowledge','box','last_scene'))
        episodes.append({'episode':ep,'title':episode['title'],'duration_s':480,'frames':11520,
                         'shots':sum(s['shots'] for s in scene_reports),'scenes':scene_reports,'video':video,'bake':bake,
                         'exit_physical_state':physical,'exit_public_facts':list(story_state['public_facts'])})
    for key in all_keys:assert (output/'pixel_cache'/(key+'.png')).is_file(),key
    jobs=[json.loads(p.read_text()) for p in (output/'jobs').glob('*/receipt.json')]
    usage={k:sum((j.get('usage') or {}).get(k,0) for j in jobs) for k in ('input_tokens','cached_input_tokens','output_tokens')}
    content=json.loads((output/'content_reviews.json').read_text()) if (output/'content_reviews.json').exists() else []
    blockers=[i for r in content for i in r['issues'] if i['severity']=='blocking']
    if blockers:
        raise ValueError('Content review blocking issues need adjudication before completion: '+json.dumps(blockers,ensure_ascii=False))
    assert len(content)==5,'Content reviews incomplete'
    contexts=json.loads((output/'context_receipts.json').read_text())
    reload_checks=json.loads((output/'saved_reload_checks.json').read_text())
    assert reload_checks['status']=='pass' and reload_checks['total_frames']==57600
    prompts=list((output/'jobs').glob('*/prompt.txt'))
    machine_receipts=[json.loads(p.read_text()) for p in (output/'production').glob('*/*/receipt.json')]
    machine_receipts += [json.loads(p.read_text()) for p in output.glob('ep??_blender_v*_receipt.json')]
    bake_receipts=[json.loads(p.read_text()) for p in output.glob('ep??_bake_receipt.json')]
    report={'status':'five_episode_capsule_previs_complete','episodes':episodes,'total_duration_s':2400,
            'total_encoded_frames':57600,'scene_count':30,'boundary_checks':continuity,
            'cross_episode_boundaries_checked':sum(c['cross_episode'] for c in continuity),
            'unique_final_pixel_states':len(all_keys),'all_pixel_cache_files':len(list((output/'pixel_cache').glob('*.png'))),
            'exact_pixel_state_reuse_fraction':1-len(all_keys)/57600,
            'model_jobs':len(jobs),'model_job_seconds':sum(j['seconds'] for j in jobs),'usage':usage,
            'context_packets':contexts,'content_reviews':content,
            'saved_scene_reload_verification':reload_checks,
            'content_volume':{'dialogue_lines':len(dialogue_texts),'unique_dialogue_lines':len(set(dialogue_texts)),
                              'dialogue_characters':sum(len(t) for t in dialogue_texts)},
            'runtime':{'wall_seconds_from_first_role_prompt':time.time()-min(p.stat().st_mtime for p in prompts),
                       'blender_production_seconds_sum':sum(r['seconds'] for r in machine_receipts),
                       'blender_export_seconds_sum':sum(r['seconds'] for r in bake_receipts),
                       'encoding_and_decode_seconds_sum':sum(e['video']['seconds'] for e in episodes),
                       'scope':'Wall starts at first role prompt; excludes earlier setup. Component sums overlap with model jobs and must not be added to obtain wall time.'},
            'limitations':['Capsule root motion and invisible attachment points; no arms/gait/physical grasp',
                           'Subtitles only, no audio or lipsync; no Seedance/Wan final rendering',
                           'Local Forest stage supplied by host; not automatic whole-scene set discovery',
                           'Walking proxy excludes GroundPlants; full current proxy forest for image rays, not original high-detail materials',
                           'Distant background omitted for RGB; EEVEE preview at 640x360, 2 samples',
                           'Scoped Codex roles with host/program feedback; not native WorldOS or native harness finalize',
                           'A new early plot edit with end-to-end re-production has not been tested in this run']}
    (output/'season_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (output/'season_script.md').write_text('\n'.join(text)+'\n')
    e=html.escape
    cards=[]
    for episode in episodes:
        ep=episode['episode'];description=next(x for x in series['episodes'] if x['id']==ep)
        first=json.loads((output/'scenes'/description['scenes'][0]['id']/'frames.json').read_text())['frame_keys'][0]
        cards.append(f'<article><h2>{ep.upper()} · {e(episode["title"])}</h2><p>{e(description["logline"])}</p>'
                     f'<video controls preload="metadata" poster="pixel_cache/{first}.png" src="{ep}.mp4"></video>'
                     f'<div class="meta">08:00 · 24 FPS · {episode["shots"]} 镜 · 11,520 帧</div>'
                     f'<div class="links"><a href="{ep}.srt">字幕</a><a href="{ep}.blend">可编辑 Blender</a>'
                     f'<a href="{ep}_video_checks.json">视频检查</a><a href="{ep}_bake_checks.json">动画回读</a></div></article>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>五集胶囊预演</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f5f7f2;color:#20362c;font:16px/1.75 system-ui,-apple-system,"PingFang SC",sans-serif}main{max-width:1080px;padding:36px 24px;margin:auto}h1{font-size:38px;margin:8px 0}h2{font-size:23px;margin:0 0 8px}p{margin:0 0 16px;color:#52675a}.eyebrow{font-size:13px;color:#267356;letter-spacing:.1em}.stats{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}.stats span{background:#e2eee3;border-radius:30px;padding:6px 14px}article{margin-top:24px;background:white;border:1px solid #d8e2d6;border-radius:16px;padding:22px}video{display:block;width:100%;max-height:620px;background:#14231c;border-radius:10px}.meta{margin:12px 0;color:#52675a;font-size:14px}.links{display:flex;gap:20px;flex-wrap:wrap}a{color:#1b674d;text-underline-offset:4px}section{margin-top:30px;padding:22px;border-radius:14px;background:#e9efe6}li{margin:8px 0}footer{font-size:14px;color:#52675a;margin:24px 0}@media(max-width:600px){main{padding:22px 14px}h1{font-size:28px}article{padding:14px}}
    video{object-fit:contain;aspect-ratio:4/3}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:9px;border-bottom:1px solid #cbd9c8}summary{cursor:pointer}details{margin-top:14px}.scroll{overflow-x:auto}
    </style><main>'''
    page+=f'<div class="eyebrow">FOREST / FIVE-EPISODE CAPSULE PREVIS</div><h1>{e(series["title"])}</h1><p>{e(series["premise"])}</p>'
    page+=f'<div class="stats"><span>5 集 × 8 分钟</span><span>30 场 · {sum(x["shots"] for x in episodes)} 镜</span><span>4 次跨集物理状态衔接已检查</span></div>'
    page+='<div class="links"><a href="season_script.md">完整剧本与拍摄方案</a><a href="season_report.json">完整证据报告</a><a href="series_plan.json">整季规划</a></div>'
    page+='<section><h2>上下文怎样控制？</h2><ul><li>编剧：固定设定、整季路线、本集场纲、精确知情/道具台账，以及最近三场摘要。前四集的全文不累积进入第五集。</li><li>动作：按集规划，按场执行；角色位置、朝向和道具归属逐场继承，跨集也不重置。</li><li>摄影：读取本集对白、动作操作及关键姿态；数值轨迹由程序计算，不把全帧数组塞给模型。</li><li>返修：保留已通过场次与像素缓存，反馈具体失败镜头；新视点仍需全帧复验。</li></ul></section>'
    names={c['id']:c['name'] for c in series['characters']}
    page+='<section><h2>四次跨集交接的实际记录</h2><div class="scroll"><table><thead><tr><th>边界</th><th>实物位置 / 持有人</th><th>已公开事实</th><th>物理末态 → 初态</th></tr></thead><tbody>'
    for i,episode in enumerate(episodes[:-1],1):
        box=episode['exit_physical_state']['box'];label={'pickup':'第一张台','drop':'第二张台'}.get(box,names.get(box,box)+'持有')
        page+=f'<tr><td>第{i}集 → 第{i+1}集</td><td>{e(label)}</td><td>{len(episode["exit_public_facts"])} 条</td><td>已核对一致</td></tr>'
    page+='</tbody></table></div><p>事实与物理状态有精确台账；人物关系、动机和承诺的全部语义尚未形式化。剧情质量仍需要创作判断。</p></section>'
    page+=''.join(cards)
    page+=f'<section><h2>本次成本与边界</h2><p>{len(jobs)} 个模型工单（含返修和内容检查），累计模型工单时间 {report["model_job_seconds"]/60:.1f} 分钟；输入 {usage["input_tokens"]:,} token，缓存输入 {usage["cached_input_tokens"]:,}，输出 {usage["output_tokens"]:,}。不含本会话、一次性开发、渲染及其他程序耗时。</p><p>最终视频引用 {len(all_keys):,} 个不同的实际 Blender 像素状态；相同状态直接复用，字幕按剧本时间更新。剧情没有靠倍速或重复场次补时长。</p><p>这是无配音的胶囊动作与摄影预演。没有人体步态、抓握、口型或 Seedance 成片；没有运行完整原生 WorldOS / harness finalize，也尚未测试一次新剧情修改后的整季重拍。</p></section><footer>全部视频完整解码；全部可编辑动画逐帧回读。采样可见性、模型内容检查与胶囊代理的通过，不等于最终影视质量或全场景物理认证。</footer></main></html>'
    (output/'index.html').write_text(page)
    print('SEASON_DELIVERED',json.dumps({k:report[k] for k in ('status','total_duration_s','total_encoded_frames','unique_final_pixel_states','model_jobs')}),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--wait',action='store_true');args=parser.parse_args()
    deliver(args.output,args.wait)
