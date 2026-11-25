"""Plan a five-episode synthetic story against the actual shared Forest stage."""
import argparse
import json
from pathlib import Path
from season.model_job import STRING as S, NUMBER as N, object_schema as O, array_schema as A, run_json
from studio_config import load_config


def validate_plan(series):
    if [e['id'] for e in series['episodes']] != [f'ep{i:02d}' for i in range(1,6)]:
        raise ValueError('Expected exactly ep01..ep05')
    if len(series['characters']) != 3 or {c['id'] for c in series['characters']} != {'A','B','C'}:
        raise ValueError('Expected three unique registered actors')
    for episode in series['episodes']:
        scenes=episode['scenes']
        if not 5<=len(scenes)<=8 or sum(s['duration_s'] for s in scenes)!=480:
            raise ValueError('Each episode needs 5–8 scenes totaling 480 seconds')
        for index,scene in enumerate(scenes,1):
            if scene['id'] != f'{episode["id"]}_s{index:02d}':
                raise ValueError('Scene IDs must be ordered safe episode-local identifiers')
            if type(scene['duration_s']) is not int or not 40<=scene['duration_s']<=120:
                raise ValueError('Scene duration outside allowed integer budget')


def plan_series(output, prior_path):
    config = load_config()
    prior = json.loads(Path(prior_path).read_text())
    fact = O({'id': S, 'text': S, 'initial_knowers': A({'type': 'string', 'enum': ['A', 'B', 'C']}, 1, 3),
              'requires': A(S), 'payoff_episode': {'type': 'integer', 'minimum': 1, 'maximum': 5}})
    scene = O({'id': S, 'duration_s': {'type': 'integer', 'minimum': 40, 'maximum': 120},
               'premise': S, 'conflict': S, 'turn': S, 'new_public_facts': A(S),
               'box_end': {'type': 'string', 'enum': ['pickup', 'drop', 'A', 'B', 'C']},
               'carry_forward': A(S)})
    episode = O({'id': S, 'title': S, 'logline': S, 'opening_dependency': A(S),
                 'cliffhanger': S, 'scenes': A(scene, 5, 8)})
    schema = O({'title': S, 'premise': S,
                'characters': A(O({'id': {'type': 'string', 'enum': ['A', 'B', 'C']},
                                   'name': S, 'motivation': S, 'secret': S}), 3, 3),
                'facts': A(fact, 8, 16), 'episodes': A(episode, 5, 5),
                'resolution': S, 'continuity_risks': A(S, 3, 8)})
    stage = {'anchors': {k: v['position'] for k, v in prior['anchors'].items()},
             'routes': prior['routes'], 'tables': prior['interaction']['tables'],
             'box_size_m': prior['interaction']['box_size_m'], 'scene_sha256': prior['source_sha256']}
    prompt = '''你是上游原创短剧的总编剧/拆集规划者。以WorldOS episode-planner的“整季事件归类、跨集因果与伏笔”思路工作，但本次是外部简化工单，不运行原生WorldOS，不继承其人工闸门。任务已获用户授权：5集，每集恰好480秒，在用户已有的同一个Forest局部影棚拍摄条纹胶囊预演。
不要调用工具；所有材料已内联。只输出满足schema的JSON。你是创作者，不允许把剧情决定交给执行器。
基础素材：森林里的证物交接，三个人围绕一个黄色盒子的归属、记录与信任产生矛盾，最后给出能闭合前四集伏笔的结局。请原创、克制、具体，可选择科研/护林/土地记录等现实题材，避免刑侦暴力。不要写同一段交接重复五次；每集有新证据、新判断、角色立场的实际转变。
物理资源仅有三人A橙/B绿/C蓝、一只不打开的黄色盒子、两张便携桌和森林空地。不能增添可见物件、电话、纸张、机关、门、汽车、火焰等。盒内内容可被谈论，但不可设计打开/读纸的动作。角色只能走位、转向、拿放或交接盒子；表演细节以对白字幕承担，不承诺人体动画。所有人同处现场，普通对白都会被三人听见，不可让C“明明在场却没听见关键对白”。可有角色选择不承认的记忆，事实与知情不能混淆。
五集是持续的一次会面，不跳时空，不无故重置人物和盒子。第1集开场A在west_entry、B在east_wait、C在observer，盒子在pickup桌。各场box_end严格传给下一场，故事安排要有拿取、交接、落台的意义。场间无传送。允许对话期间角色静止，但不靠无对白的长等待、片头片尾或重复片段填满8分钟。
每集5–8场，每场40–120秒，scenes.duration_s之和必须恰好480；时长由你依情节分配，不均分凑数。id使用ep01..ep05与ep01_s01等ASCII名。每场必须提供有区别的冲突和转折，carry_forward写后场必须承接的具体条件。
facts登记8–16条明确的客观事实，id使用F01..。initial_knowers是从开场就知道该事实的人，非全知旁白；requires列必须先知道的证据事实，不能循环。每条事实至少一个初始知情者。new_public_facts必须按真正第一次在场内公开的顺序归入场次，只出现一次；公开者必须已知或具备requires，后续可以引用但不重复标新公开。payoff_episode是对应事实用于推进/回收的集数。结局必须使用前期已埋的事实，不能第五集引入万能新证据。重点是在同一个可拍影棚内，以道具状态和空间关系承载连续叙事。
实际共享影棚：
''' + json.dumps(stage, ensure_ascii=False, separators=(',', ':'))
    result = run_json(output, 'series_writer_v1', prompt, schema, config)
    validate_plan(result)
    output = Path(output)
    (output / 'series_plan.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--prior', required=True)
    args = parser.parse_args()
    plan_series(args.output, args.prior)
