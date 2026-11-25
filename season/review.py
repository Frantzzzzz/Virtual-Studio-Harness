"""Bounded content review against actual custody timing; records issues, never rewrites."""
import argparse
import json
from pathlib import Path
from season.model_job import STRING as S, NUMBER as N, object_schema as O, array_schema as A, run_json
from studio_config import load_config


def review(output):
    output=Path(output);config=load_config();series=json.loads((output/'series_plan.json').read_text())
    schema=O({'episode_id':S,'assessment':S,'issues':A(O({'severity':{'type':'string','enum':['blocking','note']},
             'scene':S,'start_s':N,'owner':{'type':'string','enum':['writer','action','camera']},
             'evidence':S,'reason':S,'suggested_minimal_fix':S}),0,12)})
    previous=None;reports=[]
    for episode in series['episodes']:
        scripts=json.loads((output/f'{episode["id"]}_script.json').read_text())
        scene_inputs=[]
        for outline,script in zip(episode['scenes'],scripts['scenes']):
            motion=json.loads((output/'scenes'/outline['id']/'motion.json').read_text())
            lines=[]
            for line in script['dialogue']:
                before=motion['samples'][min(len(motion['samples'])-1,round(line['start_s']*24))]['props']['box']['owners']
                after=motion['samples'][min(len(motion['samples'])-1,max(0,round(line['end_s']*24)-1))]['props']['box']['owners']
                lines.append(dict(line,actual_box_owners_at_start=before,actual_box_owners_at_end=after))
            scene_inputs.append({'outline':outline,'summary':script['summary'],'lines':lines,
                                 'actual_entry':motion['entry'],'actual_exit':motion['exit'],'actual_prop_events':motion['events']})
        packet={'title':series['title'],'characters':series['characters'],'facts':series['facts'],
                'entry_story_state':previous,'episode':episode,'scenes':scene_inputs}
        prompt='''你是内容连续性质检。请独立检查本集完整对白和实际已编译的道具持有时序，不修改任何文件，不调用工具，只输出JSON。重点找可定位的硬问题：①首次公开前就提前说出了关键事实；②说话者不可能知道的事实；③对白声称“现在在某人手里/已经放下”与实际owners或事件时刻冲突；④同一场或跨集实物凭空重置；⑤结论超出了已公开证据、声称已完成影棚外的行动。所有三人都在场，普通对白都会听见。
不要把角色的疑问、否认、未来承诺、比喻或明确的回忆误当作当前客观事实。知情不等于已公开。只有明确证据才标blocking；不确定或审美建议标note，并解释不确定。可接受胶囊根节点移动、转向和不可见挂点，不能因没有手臂/口型/步态批评本实验。没有音轨，角色对白用字幕承担。全季都在同一森林空地，盒子始终不打开，未做外部档案修改。
不要机械相信uses_facts/reveals_facts标签，要读实际句子。对没有硬冲突的集如实写issues=[]，不用编造缺点。assessment给简短结论，每个issue给出场次、时间、实际证据和最小修正，不能泛泛而谈。
''' + json.dumps(packet,ensure_ascii=False,separators=(',',':'))
        result=run_json(output,f'{episode["id"]}_continuity_review_v1',prompt,schema,config)
        reports.append(result)
        (output/'content_reviews.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
        previous=json.loads((output/f'{episode["id"]}_story_state.json').read_text())
        previous.pop('history',None)
        print('CONTENT_REVIEW',episode['id'],[(i['severity'],i['scene']) for i in result['issues']],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args();review(args.output)
