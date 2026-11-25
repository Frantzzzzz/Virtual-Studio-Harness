"""Episode writer with exact knowledge state and bounded context per job."""
import argparse
import json
from pathlib import Path
from season.model_job import STRING as S, NUMBER as N, object_schema as O, array_schema as A, run_json
from season.continuity import initial_state, context_packet, check_scene_script
from studio_config import load_config


def write_episodes(output):
    output = Path(output)
    config = load_config()
    series = json.loads((output / 'series_plan.json').read_text())
    state = initial_state(series)
    line_schema = O({'start_s': N, 'end_s': N, 'speaker': {'type': 'string', 'enum': ['A', 'B', 'C']},
                     'text': S, 'uses_facts': A(S), 'reveals_facts': A(S)})
    scene_schema = O({'id': S, 'summary': S, 'box_end': {'type': 'string', 'enum': ['pickup', 'drop', 'A', 'B', 'C']},
                      'dialogue': A(line_schema, 5, 25),
                      'blocking_intents': A(O({'start_s': N, 'end_s': N, 'description': S}), 1, 8)})
    schema = O({'episode_id': S, 'scenes': A(scene_schema, 5, 8), 'ending_summary': S})
    context_receipts = []
    for episode in series['episodes']:
        packet = context_packet(series, episode, state)
        prompt = '''你是上游编剧/对白指导，按已接受的整季规划写本集完整的480秒字幕式胶囊预演剧本。采用WorldOS screenplay的“可拍动作、角色与场景合法引用、跨场因果”原则；这是独立简化工单，不是原生WorldOS，无需调用其工具或闸门。不要调用任何工具，全部信息内联，只返回schema的JSON。
你负责剧情和时间，不让动作或摄影执行器填内容。不要增加人物、可见道具、场地、电话、画外人、跳时或盒子开合；只有三人、两张台、封闭黄盒与森林。可以讨论已有记忆和记录，但不能读不存在的纸或屏幕。前集结尾精确传入下集开头。
本集场次、每场时长、box_end、新公开facts列表以规划为准。每场是实时时间，dialogue的时间为场内秒，从0附近持续覆盖到场尾，顺序无重叠。时间都用0.5秒整数倍。不要靠空等、反复说同一句或片头片尾凑时长。每场对白覆盖>=75%时间，任意两句间隔<=4秒、结尾空白<=4秒；每秒实际字幕字数合理范围1.8–7，每场总对白字数至少duration*2.7，目标3.2–4.0字/秒。每句尽量30–65字，对应8–18秒，长句可自然分开。对白要有具体利益、追问、误判与纠正，不用旁白说明“他们讨论了很久”。胶囊暂时没有口型，对白将以字幕呈现。
知识机检：uses_facts只列该说话人此时已知的事实；reveals_facts是这句真正第一次向所有在场者公开的事实，该说话人必须是initial_knower，或此前已经听到它；其requires必须在此前已公开。一次公开后三人全部知道，在后句可使用，不能再次标reveals。每场reveals集合必须等于规划new_public_facts。不得在事实正式公开前用对白提前泄露；不确定和质问要写成质问，不当作已证实结论。
blocking_intents给动作导演的上游意图与时间窗口，需落地拿/放/交接、对视、靠近或退开，不写坐卧、手指、打开盒子等超出占位人偶的表演。每场box_end要达到规划要求：pickup/drop表示放在对应桌，A/B/C表示由对应角色持有。不要强制每场都搬盒；有叙事动机才动。summary最多100汉字，记录真正改变的关系/信息与未决条件，供后续场次按需回读。
完整输入（精确知情状态由ledger提供；recent summaries不是事实权威）：
''' + json.dumps(packet, ensure_ascii=False, separators=(',', ':'))
        accepted = None
        for revision in range(4):
            result = run_json(output, f'{episode["id"]}_writer_v{revision+1}', prompt, schema, config)
            errors, reports = [], []
            current = json.loads(json.dumps(state))
            if result['episode_id'] != episode['id'] or [s['id'] for s in result['scenes']] != [s['id'] for s in episode['scenes']]:
                errors.append('Episode/scene IDs changed')
            else:
                for scene, script in zip(episode['scenes'], result['scenes']):
                    current, issues, stats = check_scene_script(scene, script, current, series)
                    errors.extend(f'{scene["id"]}: {e}' for e in issues)
                    reports.append({'scene': scene['id'], **stats})
            (output / f'{episode["id"]}_writing_check_v{revision+1}.json').write_text(json.dumps({'errors': errors, 'stats': reports}, ensure_ascii=False, indent=2))
            if not errors:
                accepted = result
                state = current
                break
            prompt = ('你是原编剧，修正下面机检定位的问题，保留正确剧情与对白，仍输出本集完整JSON。不改既定场次、时长与事实公开归属。不要调用工具。\n'
                      + json.dumps({'original_input': packet, 'previous_script': result, 'errors': errors}, ensure_ascii=False, separators=(',', ':')))
        if accepted is None:
            raise RuntimeError(f'{episode["id"]} still violates continuity/pacing; see checks')
        (output / f'{episode["id"]}_script.json').write_text(json.dumps(accepted, ensure_ascii=False, indent=2) + '\n')
        (output / f'{episode["id"]}_story_state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
        context_receipts.append({'episode': episode['id'], 'packet_characters': len(json.dumps(packet, ensure_ascii=False)),
                                 'recent_summaries_loaded': len(packet['recent_scene_summaries']),
                                 'all_prior_raw_scripts_loaded': False, 'revisions': revision+1})
        (output / 'context_receipts.json').write_text(json.dumps(context_receipts, ensure_ascii=False, indent=2) + '\n')
        print('EPISODE_SCRIPT_ACCEPTED', episode['id'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        write_episodes(args.output)
    except Exception as error:
        (Path(args.output) / 'writer_failed.json').write_text(json.dumps({'error': str(error)}))
        raise
