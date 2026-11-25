"""Authoritative story state, bounded context and dependency invalidation."""
import copy
from season.model_job import digest

ACTORS = ('A', 'B', 'C')


def initial_state(series):
    facts = {f['id']: f for f in series['facts']}
    if len(facts) != len(series['facts']):
        raise ValueError('Duplicate fact ID')
    for fact in facts.values():
        if not set(fact['initial_knowers']) <= set(ACTORS) or not fact['initial_knowers']:
            raise ValueError('Unknown or missing initial knower')
        if not set(fact['requires']) <= set(facts):
            raise ValueError('Unknown prerequisite fact')
    visiting, visited = set(), set()
    def visit(fid):
        if fid in visiting:
            raise ValueError('Cyclic fact dependency')
        if fid in visited:
            return
        visiting.add(fid)
        for parent in facts[fid]['requires']:
            visit(parent)
        visiting.remove(fid)
        visited.add(fid)
    for fid in facts:
        visit(fid)
    return {'public_facts': [],
            'knowledge': {a: sorted(f['id'] for f in facts.values() if a in f['initial_knowers']) for a in ACTORS},
            'box': 'pickup', 'last_scene': None, 'history': []}


def check_scene_script(scene, script, state, series):
    """Walk actual dialogue in time order; knowledge never comes from a summary."""
    result = copy.deepcopy(state)
    errors = []
    facts = {f['id']: f for f in series['facts']}
    duration = scene['duration_s']
    last = 0.
    revealed = []
    characters = 0
    speech_seconds = 0.
    for index, line in enumerate(script['dialogue']):
        a, b, actor = line['start_s'], line['end_s'], line['speaker']
        if actor not in ACTORS or not (0 <= a < b <= duration) or a < last - 1e-7:
            errors.append(f'dialogue {index}: invalid speaker/time or overlapping dialogue')
            continue
        if a - last > 4:
            errors.append(f'dialogue {index}: unexplained silent gap {a-last:.2f}s')
        last = b
        length = len(line['text'].replace(' ', ''))
        characters += length
        speech_seconds += b - a
        if length / (b - a) > 7 or length / (b - a) < 1.8:
            errors.append(f'dialogue {index}: implausible subtitle pace {length/(b-a):.2f} chars/s')
        for fid in line['uses_facts']:
            if fid not in facts or fid not in result['knowledge'][actor]:
                errors.append(f'dialogue {index}: {actor} uses unknown fact {fid}')
        for fid in line['reveals_facts']:
            if fid not in facts or fid not in result['knowledge'][actor]:
                errors.append(f'dialogue {index}: {actor} reveals unknown fact {fid}')
                continue
            if fid in result['public_facts']:
                errors.append(f'dialogue {index}: fact {fid} already public')
                continue
            missing = set(facts[fid]['requires']) - set(result['public_facts'])
            if missing:
                errors.append(f'dialogue {index}: missing public evidence {sorted(missing)} for {fid}')
            result['public_facts'].append(fid)
            revealed.append(fid)
            # All three actors are physically present and can hear ordinary dialogue.
            for aid in ACTORS:
                if fid not in result['knowledge'][aid]:
                    result['knowledge'][aid].append(fid)
    if duration - last > 4:
        errors.append(f'unexplained trailing silence: {duration-last:.2f}s')
    if set(revealed) != set(scene['new_public_facts']):
        errors.append(f'reveal mismatch: wanted {scene["new_public_facts"]}, got {revealed}')
    if speech_seconds < duration * .75:
        errors.append('Dialogue covers less than 75% of scene; cannot fill duration with idle holds')
    if characters < duration * 2.7:
        errors.append('Insufficient dialogue content for the scene budget')
    if script['box_end'] != scene['box_end']:
        errors.append('Writer changed outline custody target')
    result['box'] = script['box_end']
    result['last_scene'] = scene['id']
    result['history'].append({'scene': scene['id'], 'summary': script['summary'],
                              'public_facts': revealed, 'box_end': script['box_end']})
    return result, errors, {'dialogue_characters': characters, 'speech_seconds': speech_seconds}


def context_packet(series, episode, state):
    """Immutable bible + exact ledger + short recent summaries, not an ever-growing chat."""
    packet = {'title': series['title'], 'premise': series['premise'],
              'characters': series['characters'], 'facts': series['facts'],
              'season_roadmap': [{'id': e['id'], 'logline': e['logline'], 'cliffhanger': e['cliffhanger']}
                                 for e in series['episodes']],
              'episode': episode,
              'entry_state': {k: copy.deepcopy(v) for k, v in state.items() if k != 'history'},
              'recent_scene_summaries': copy.deepcopy(state['history'][-3:])}
    return packet


def affected_artifacts(changed, dependencies):
    """Transitive downstream closure: a camera-only change never invalidates story."""
    affected = set(changed)
    while True:
        found = {name for name, parents in dependencies.items() if set(parents) & affected}
        if found <= affected:
            return affected
        affected |= found


def receipt_inputs(inputs):
    return {key: digest(value) for key, value in inputs.items()}
