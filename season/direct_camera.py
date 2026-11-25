"""Scene-level photography intent; numeric view solving stays in the harness."""
import argparse
import json
from pathlib import Path
import time
from season.model_job import STRING as S, NUMBER as N, object_schema as O, array_schema as A, run_json
from studio_config import load_config


def direct_camera(output):
    output = Path(output)
    config = load_config()
    series = json.loads((output / 'series_plan.json').read_text())
    nullable_actor = {'anyOf': [{'type': 'string', 'enum': ['A', 'B', 'C']}, {'type': 'null'}]}
    shot = O({'id': S, 'start_s': N, 'end_s': N,
              'subjects': A({'type': 'string', 'enum': ['A', 'B', 'C', 'box']}, 1, 4),
              'lens_mm': {'type': 'number', 'minimum': 18, 'maximum': 50},
              'projected_height': {'type': 'number', 'minimum': .25, 'maximum': .8},
              'allowed_azimuths_deg': A({'type': 'number', 'enum': [-150, -90, -30, 30, 90, 150]}, 2, 6),
              'allowed_elevations_deg': A({'type': 'number', 'enum': [10, 25, 40]}, 1, 3),
              'motion': {'type': 'string', 'enum': ['static', 'follow_actor']},
              'follow_actor': nullable_actor, 'intent': S})
    schema = O({'episode_id': S, 'design_rationale': S,
                'scenes': A(O({'id': S, 'shots': A(shot, 3, 12)}), 6, 6)})
    for episode in series['episodes']:
        schema['properties']['scenes']['minItems']=len(episode['scenes'])
        schema['properties']['scenes']['maxItems']=len(episode['scenes'])
        action_path = output / f'{episode["id"]}_action_plan.json'
        while not action_path.exists():
            if (output / 'actions_failed.json').exists():
                raise RuntimeError('Actions failed; camera director stopped')
            time.sleep(5)
        actions = json.loads(action_path.read_text())
        script = json.loads((output / f'{episode["id"]}_script.json').read_text())
        scene_inputs = []
        for outline, screenplay, action in zip(episode['scenes'], script['scenes'], actions['scenes']):
            motion = json.loads((output / 'scenes' / outline['id'] / 'motion.json').read_text())
            times = {0, outline['duration_s']-1/24}
            for op in action['operations']:
                times.update(t for name in ('start_s', 'contact_s', 'transfer_s', 'end_s') if (t := op[name]) is not None)
            rows = [motion['samples'][min(len(motion['samples'])-1, round(t*24))] for t in sorted(times)]
            scene_inputs.append({'outline': outline, 'script': screenplay, 'action_plan': action,
                                 'entry': motion['entry'], 'exit': motion['exit'], 'key_pose_samples': rows})
        packet = {'episode': episode['id'], 'title': series['title'], 'characters': series['characters'], 'scenes': scene_inputs}
        prompt = '''你是摄影指导，按已锁定的剧本和实际动作编排本集每场拍摄。采用WorldOS camera-movement的“剧情驱动拍法、空间连续、交接过程不漏”原则；本次是外部camera harness工单，不跑原生WorldOS。不要调用任何工具，全部数据内联，只返回JSON。
每场shots连续覆盖0..场时长，不重叠不留白，起止都用0.5秒倍数。每镜通常8–24秒，可因交接延长，但不要把整场只拍一个机位或机械等分。id全局唯一，使用场ID加_sh01等。动作时间、站位、盒子归属与对白不得修改。
摄影参数由你决定：subjects列必须看清的主体，A/B/C指头部主体，box指黄盒。对话近景可只要求当前说话者；双人镜选二人；首场首镜必须三人和盒子同框交代空间。take/put/give整个start_s..end_s必须包含在同一个镜头中，不能在接触归属变化中切镜；该镜subjects必须包含动作所有参与人和box。不要为每句台词都切镜，配合追问、反应和立场变化。其他画外人物仍真实存在，不得藏人。
camera harness会根据subjects真实包围盒、lens_mm、projected_height（画面高度占比）计算距离。allowed_azimuths_deg与allowed_elevations_deg是你授权的有限摄影方位范围：程序只在其中搜索并选择全帧几何/可见性通过的候选；你负责范围与构图意图，程序不能超出范围，也不能挪演员。方位角是Blender世界XY方位，并非人物自身坐标。为林地遮挡保留至少两个候选方位，建议对话镜保留四到六个候选，俯角10或25；开场全景18–24mm、height .30–.45，人物近景28–40mm、height .45–.65。实际执行可能反馈没有可用摄影解，需要你返修镜头或请求动作导演协商。
motion=static固定在本镜中点实际姿态求解的机位和关注点；移动会出画时你应改用follow_actor或切开动作区间。motion=follow_actor需指定follow_actor，对该角色根节点做同量平移跟随，保持相对偏移与摄影方向；静态镜follow_actor=null。跟拍也会检查树木与人物碰撞，不能假定永远可行。拿放和面对面交接通常用静态镜，走位可跟随。
请让五集保持同一导演语言：交代空间→有动机地近看发言/反应→关键物件动作给足完整过程。只增加有叙事作用的镜头。给每镜intent说明关键画面信息与允许候选的取舍。不要承诺程序还没测过的无碰撞或可见性。
输入：
''' + json.dumps(packet, ensure_ascii=False, separators=(',', ':'))
        result = run_json(output, f'{episode["id"]}_camera_v1', prompt, schema, config)
        errors = validate_camera(episode, result, actions)
        for revision in range(1, 4):
            if not errors:
                break
            feedback = {'original_input': packet, 'previous_plan': result, 'errors': errors}
            result = run_json(output, f'{episode["id"]}_camera_v{revision+1}',
                              '你是原摄影指导，按以下明确反馈修正完整本集摄影计划，不改变动作或剧本，不调用工具。\n'
                              + json.dumps(feedback, ensure_ascii=False, separators=(',', ':')), schema, config)
            errors = validate_camera(episode, result, actions)
        if errors:
            raise RuntimeError(str(errors))
        (output / f'{episode["id"]}_camera_plan.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print('EPISODE_CAMERA_INTENT_READY', episode['id'], flush=True)


def validate_camera(episode, result, actions):
    errors = []
    if [s['id'] for s in result['scenes']] != [s['id'] for s in episode['scenes']]:
        return ['Wrong scene IDs/order']
    for outline, plan, action in zip(episode['scenes'], result['scenes'], actions['scenes']):
        cursor = 0
        for shot in plan['shots']:
            if shot['start_s'] != cursor or shot['end_s'] <= cursor:
                errors.append(f'{outline["id"]}: discontinuous shot at {shot["id"]}')
            cursor = shot['end_s']
            if any(abs(t*24-round(t*24)) > 1e-6 for t in (shot['start_s'], shot['end_s'])):
                errors.append('Shot times off frame grid')
            if (shot['motion'] == 'static') != (shot['follow_actor'] is None):
                errors.append('Follow actor inconsistent with camera motion')
        if cursor != outline['duration_s']:
            errors.append(f'{outline["id"]}: camera does not cover full scene duration')
        for op in action['operations']:
            if op['kind'] not in ('take', 'put', 'give'):
                continue
            required = {op['actor'], 'box'} | ({op['other']} if op['kind'] == 'give' else set())
            if not any(s['start_s'] <= op['start_s'] and s['end_s'] >= op['end_s']
                       and required <= set(s['subjects']) for s in plan['shots']):
                errors.append(f'{outline["id"]}: contact action {op["kind"]} {op["start_s"]}-{op["end_s"]} not covered intact')
    if set(result['scenes'][0]['shots'][0]['subjects']) != {'A', 'B', 'C', 'box'} and episode['id'] == 'ep01':
        errors.append('Season opening must show all actors and box')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        direct_camera(args.output)
    except Exception as error:
        (Path(args.output) / 'camera_failed.json').write_text(json.dumps({'error': str(error)}))
        raise
