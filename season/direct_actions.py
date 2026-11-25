"""Action director jobs; measured execution feedback goes back to that role."""
import argparse
import json
from pathlib import Path
import sys
import time
from season.model_job import STRING as S, NUMBER as N, object_schema as O, array_schema as A, run_json
from season.motion import compile_scene, initial_physical_state
from studio_config import load_config


def direct_actions(output, prior_dir):
    output, prior_dir = Path(output), Path(prior_dir)
    config = load_config()
    sys.path[:0] = [str(config['camera_harness']), str(config['worldos'])]
    from modules.whitebox import sample
    from camera_agent.motion.standin_samples import compile_standin_samples
    studio = json.loads((prior_dir / 'shared_studio.json').read_text())
    navigation = json.loads((prior_dir / 'navigation_details.json').read_text())
    series = json.loads((output / 'series_plan.json').read_text())
    optional_time = {'anyOf': [N, {'type': 'null'}]}
    optional_actor = {'anyOf': [{'type': 'string', 'enum': ['A', 'B', 'C']}, {'type': 'null'}]}
    operation = O({'kind': {'type': 'string', 'enum': ['move', 'face', 'take', 'put', 'give']},
                   'actor': {'type': 'string', 'enum': ['A', 'B', 'C']}, 'other': optional_actor,
                   'route': A(S), 'site': {'anyOf': [{'type': 'string', 'enum': ['pickup', 'drop']}, {'type': 'null'}]},
                   'start_s': N, 'contact_s': optional_time, 'transfer_s': optional_time, 'end_s': N})
    schema = O({'episode_id': S, 'design_rationale': S,
                'scenes': A(O({'id': S, 'operations': A(operation, 0, 25), 'blocking_description': S}), 6, 6)})
    state = initial_physical_state()
    scene_manifest = []
    for episode in series['episodes']:
        schema['properties']['scenes']['minItems']=len(episode['scenes'])
        schema['properties']['scenes']['maxItems']=len(episode['scenes'])
        script_path = output / f'{episode["id"]}_script.json'
        while not script_path.exists():
            if (output / 'writer_failed.json').exists():
                raise RuntimeError('Writer failed; action director stopped rather than fabricating a script')
            time.sleep(5)
        script = json.loads(script_path.read_text())
        stage = {'anchors': {k: v['position'] for k, v in studio['anchors'].items()},
                 'routes': studio['routes'], 'sites': studio['interaction'],
                 'navigation_scope': 'Only measured edges, sphere proxy, not original high-detail physics'}
        episode_input = [{'outline': s, 'script': t} for s, t in zip(episode['scenes'], script['scenes'])]
        packet = {'episode': episode['id'], 'entry_physical_state': state, 'stage': stage,
                  'scenes': episode_input, 'characters': series['characters']}
        prompt = '''你是上游动作导演，为既有Forest影棚中的三名胶囊人决定本集每场动作。你负责走位、时刻、转向与道具归属；程序只展开你选的动作。采用WorldOS白模调度的“在场人物一致、轨迹完整、防穿模、交接可见”原则；这是独立工单，不运行原生WorldOS。不要调用任何工具，所有材料内联，只返回完整JSON。
动作库：
move：actor沿route列出的锚点顺序移动，route第一点必须是该人当时真实所在锚点，至少两点，边必须在routes中（可反向）。程序沿实测地面路径匀速展开，总速度0.12–1.8m/s。保持原朝向；若要朝前行进，先face。other/site/contact_s/transfer_s均null。
face：actor在start_s至end_s内转向other；或other=null且route只含一个目标锚点。最大转速240度/秒。site/contact_s/transfer_s=null。面向他人按真实位置计算，不复制yaw。
take：actor必须先到pickup_stand或drop_stand，site选对应桌，start_s准备，contact_s到达盒子并成为持有人，transfer_s=contact_s，end_s收至腹前。route=[]、other=null。准备/恢复各>=0.25秒。
put：actor是唯一持有人，先到对应stand，site选对应桌。contact_s到桌面，transfer_s释放，end_s收回挂点。route=[]、other=null，接触到释放建议0.5秒。
give：actor是持有人，other是接收人；两人必须先分别站在handover_A与handover_B，谁在左右皆可；start_s准备，contact_s双方到共同挂点并共同持有，transfer_s原持有人松开，end_s恢复。共同持有至少0.4秒，准备/恢复各>=0.25秒。route=[]、site=null。只有在该交接节点才能交盒。
所有时间为场内秒，0.5秒倍数，在0..场时长内。move/face不需要的字段填null或空列表。不要制造不存在的动作。三人保持在场。每场box_end必须达到编剧指定状态，人物锚点与朝向从上一场末状态继承；不能跳时空、传送、重新摆演员或重置盒子。接触动作期间涉及的角色都不能移动根节点，同一角色不能有两个重叠接触动作。
避让很重要：三人体中心距离至少0.64m，不能把静止的人当不存在，不能让两人同时走向一个锚点或相向穿过。拿取/落台前要让先占stand的人撤到空锚点；交接前要让第三人避开交接区。空间冲突应在你这里调整路线或时刻，不让摄影掩盖。
接触前先face到桌面方向或交接对象，对话期间尽量互相面向。可利用动作改变人物关系，但不要重复绕圈或无理由等待。对白占据大部分时间是可接受的，动作在编剧blocking_intents的窗口内完成，不能改编剧对白、揭示顺序或每场时长。每场给blocking_description，解释怎样服务剧情。
你有六场的完整文本与初态。顺序模拟自己安排的末态，再为下一场规划。无需等额分动作，没必要移动的场次可以仅face或operations=[]。给出的所有数值都要可执行。
输入：
''' + json.dumps(packet, ensure_ascii=False, separators=(',', ':'))
        if len(episode['scenes'])!=6:
            prompt=prompt.replace('六场',str(len(episode['scenes']))+'场')
        accepted = None
        for revision in range(5):
            result = run_json(output, f'{episode["id"]}_actions_v{revision+1}', prompt, schema, config)
            current = json.loads(json.dumps(state))
            compiled, errors = [], []
            if [s['id'] for s in result['scenes']] != [s['id'] for s in episode['scenes']]:
                errors.append('Wrong scene IDs/order')
            else:
                for scene, plan in zip(episode['scenes'], result['scenes']):
                    try:
                        rows = compile_scene(scene, plan, current, studio, navigation, sample, compile_standin_samples)
                        compiled.append((scene, plan, rows))
                        current = rows['exit']
                    except ValueError as error:
                        errors.append({'scene': scene['id'], 'entry': current, 'error': str(error)})
                        break
            (output / f'{episode["id"]}_action_check_v{revision+1}.json').write_text(json.dumps({'errors': errors}, ensure_ascii=False, indent=2))
            if not errors:
                accepted = result
                state = current
                break
            prompt = ('你是原动作导演。以下是真实编译失败反馈，请局部修正，仍返回本集六场完整计划。保留正确场次，不能更改剧情、场长或归属目标。不要调用工具。\n'
                      + json.dumps({'original_input': packet, 'previous_plan': result, 'execution_feedback': errors}, ensure_ascii=False, separators=(',', ':')))
        if accepted is None:
            raise RuntimeError(f'{episode["id"]}: action plan still fails; see action checks')
        (output / f'{episode["id"]}_action_plan.json').write_text(json.dumps(accepted, ensure_ascii=False, indent=2))
        for scene, plan, data in compiled:
            directory = output / 'scenes' / scene['id']
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'motion.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
            (directory / 'action_plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2))
            scene_manifest.append({'id': scene['id'], 'episode': episode['id'], 'duration_s': scene['duration_s'],
                                   'entry': data['entry'], 'exit': data['exit'], 'motion_diagnostics': data['diagnostics']})
        (output / 'scene_manifest.json').write_text(json.dumps(scene_manifest, ensure_ascii=False, indent=2))
        print('EPISODE_ACTIONS_ACCEPTED', episode['id'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--prior-dir', required=True)
    args = parser.parse_args()
    try:
        direct_actions(args.output, args.prior_dir)
    except Exception as error:
        (Path(args.output) / 'actions_failed.json').write_text(json.dumps({'error': str(error)}))
        raise
