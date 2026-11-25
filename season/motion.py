"""Timed capsule primitives with persistent roots and explicit prop custody.

The director chooses primitive, route and every time. This compiler expands those
choices; it cannot create a new route, stretch a scene or reset an actor.
"""
import bisect
import copy
import math

ACTORS = ('A', 'B', 'C')


def quaternion_angle_error(first, second):
    denominator=math.sqrt(sum(v*v for v in first)*sum(v*v for v in second))
    if not denominator:
        raise ValueError('Zero quaternion')
    dot=abs(sum(a*b for a,b in zip(first,second)))/denominator
    return 2*math.acos(min(1.,dot))


def initial_physical_state():
    return {'actors': {'A': {'node': 'west_entry', 'yaw': math.pi/2},
                       'B': {'node': 'east_wait', 'yaw': -math.pi/2},
                       'C': {'node': 'observer', 'yaw': 0.}}, 'box': 'pickup'}


def lerp(a, b, fraction):
    return [x + (y-x)*fraction for x, y in zip(a, b)]


def along(path, fraction):
    lengths = [math.dist(a, b) for a, b in zip(path, path[1:])]
    distance = sum(lengths) * max(0., min(1., fraction))
    for a, b, length in zip(path, path[1:], lengths):
        if distance <= length + 1e-9:
            return lerp(a, b, 0. if not length else max(0., min(1., distance/length)))
        distance -= length
    return list(path[-1])


def compile_scene(scene, plan, entry, studio, navigation, sample, compile_standin_samples, fps=24):
    duration = scene['duration_s']
    count = round(duration * fps)
    anchors = {name: a['position'] for name, a in studio['anchors'].items()}
    routes = {frozenset((r['from'], r['to'])): r for r in navigation['routes']}
    sites = {site: studio['interaction'][site + '_box'] for site in ('pickup', 'drop')}
    def require(value, message):
        if not value:
            raise ValueError(message)
    def time(t):
        require(type(t) in (int, float) and 0 <= t <= duration and abs(t*fps-round(t*fps)) < 1e-6,
                f'Time not on scene frame grid: {t}')
    operations = sorted(copy.deepcopy(plan['operations']), key=lambda x: x['start_s'])
    moves = {a: [] for a in ACTORS}
    faces = {a: [] for a in ACTORS}
    hands = {a: [] for a in ACTORS}
    node_history = {a: entry['actors'][a]['node'] for a in ACTORS}
    last_move_end = {a: -1 for a in ACTORS}
    for operation in operations:
        a, kind = operation['actor'], operation['kind']
        require(a in ACTORS, 'Unknown actor')
        time(operation['start_s']); time(operation['end_s'])
        require(operation['end_s'] > operation['start_s'], 'Empty operation')
        if kind == 'move':
            route_nodes = operation['route']
            require(len(route_nodes) >= 2 and route_nodes[0] == node_history[a], f'{a}: route does not start at actual node {node_history[a]}')
            require(operation['start_s'] >= last_move_end[a], f'{a}: overlapping moves')
            path = []
            for first, last in zip(route_nodes, route_nodes[1:]):
                require(frozenset((first, last)) in routes, f'Unmeasured route {first} -> {last}')
                route = routes[frozenset((first, last))]
                points = route['path'] if route['from'] == first else list(reversed(route['path']))
                path += points if not path else points[1:]
            speed = sum(math.dist(x, y) for x, y in zip(path, path[1:])) / (operation['end_s']-operation['start_s'])
            require(.12 <= speed <= 1.8, f'{a}: implausible walking speed {speed:.3f}')
            operation['path'] = path
            moves[a].append(operation)
            node_history[a] = route_nodes[-1]
            last_move_end[a] = operation['end_s']
        elif kind == 'face':
            faces[a].append(operation)
        elif kind in ('take', 'put', 'give'):
            for t in ('contact_s', 'transfer_s'):
                require(operation[t] is not None, f'{kind} needs {t}')
                time(operation[t])
            require(operation['start_s']+.25 <= operation['contact_s'] <= operation['transfer_s'] <= operation['end_s']-.25,
                    f'{kind}: insufficient contact preparation/recovery')
            if kind == 'give':
                require(operation['other'] in ACTORS and operation['other'] != a, 'Invalid handover partner')
                require(operation['transfer_s']-operation['contact_s'] >= .4, 'Joint hold must be visible')
                hands[operation['other']].append(operation)
            else:
                require(operation['site'] in sites, 'Unknown table')
            hands[a].append(operation)
        else:
            raise ValueError('Unknown capsule primitive: ' + kind)
    def root(a, t):
        position = list(anchors[entry['actors'][a]['node']])
        for op in moves[a]:
            if t < op['start_s']:
                break
            if t <= op['end_s']:
                return along(op['path'], (t-op['start_s'])/(op['end_s']-op['start_s']))
            position = list(op['path'][-1])
        return position
    def face_target(a, op):
        if op['other'] in ACTORS:
            return root(op['other'], op['end_s'])
        require(len(op['route']) == 1 and op['route'][0] in anchors, 'Face needs another actor or one target anchor')
        return anchors[op['route'][0]]
    headings = {a: [] for a in ACTORS}
    for a in ACTORS:
        value = entry['actors'][a]['yaw']
        end = -1
        for op in faces[a]:
            require(op['start_s'] >= end, f'{a}: overlapping turns')
            p, target = root(a, op['end_s']), face_target(a, op)
            require(math.hypot(p[0]-target[0], p[2]-target[2]) > .01, 'Zero facing target')
            target_yaw = math.atan2(target[0]-p[0], target[2]-p[2])
            delta = (target_yaw-value+math.pi) % (2*math.pi)-math.pi
            require(abs(delta)/(op['end_s']-op['start_s']) <= math.radians(240), 'Turn too fast')
            headings[a].append((op['start_s'], op['end_s'], value, delta))
            value += delta
            end = op['end_s']
    def yaw(a, t):
        value = entry['actors'][a]['yaw']
        for start, end, first, delta in headings[a]:
            if t < start:
                break
            value = first + delta*min(1., (t-start)/(end-start))
        return value
    def offset(a, t, holding):
        p, angle = root(a, t), yaw(a, t)
        z = .35 if holding else .08
        return [p[0]+math.sin(angle)*z, p[1]+1.02, p[2]+math.cos(angle)*z]
    events = []
    free = [{'t': 0, 'position': sites.get(entry['box'], sites['pickup']), 'hold': True}]
    owners = [] if entry['box'] in sites else [entry['box']]
    for op in operations:
        kind, a = op['kind'], op['actor']
        if kind not in ('take', 'put', 'give'):
            continue
        require(math.dist(root(a, op['start_s']), root(a, op['end_s'])) < 1e-7, 'Root moves during contact action')
        if kind in ('take', 'put'):
            expected = 'pickup_stand' if op['site'] == 'pickup' else 'drop_stand'
            require(math.dist(root(a, op['start_s']), anchors[expected]) < 1e-7, f'{kind}: {a} must stand at {expected}')
        else:
            b = op['other']
            require(math.dist(root(b, op['start_s']), root(b, op['end_s'])) < 1e-7, 'Receiver moves during handover')
            pair = [root(a, op['start_s']), root(b, op['start_s'])]
            expected = [anchors['handover_A'], anchors['handover_B']]
            require(all(any(math.dist(p, e) < 1e-7 for e in expected) for p in pair) and math.dist(*pair) > .6,
                    'Handover requires the two measured meeting anchors')
        if kind == 'take':
            events.append({'t': op['contact_s'], 'kind': 'take', 'actor': a, 'site': op['site']})
        elif kind == 'put':
            events.append({'t': op['transfer_s'], 'kind': 'put', 'actor': a, 'site': op['site']})
            free.append({'t': op['transfer_s'], 'position': sites[op['site']], 'hold': True})
        else:
            events += [{'t': op['contact_s'], 'kind': 'join', 'actor': b, 'giver': a},
                       {'t': op['transfer_s'], 'kind': 'release', 'actor': a}]
    events.sort(key=lambda e: e['t'])
    current_site = entry['box'] if entry['box'] in sites else None
    states = []
    receipts = []
    cursor = 0
    for i in range(count+1):
        t = i/fps
        while cursor < len(events) and events[cursor]['t'] <= t+1e-8:
            e = events[cursor]
            before = list(owners)
            if e['kind'] == 'take':
                require(not owners and current_site == e['site'], 'Take from wrong table or already-held box')
                owners = [e['actor']]; current_site = None
            elif e['kind'] == 'put':
                require(owners == [e['actor']], 'Put by non-owner')
                owners = []; current_site = e['site']
            elif e['kind'] == 'join':
                require(owners == [e['giver']], 'Join wrong giver')
                owners.append(e['actor'])
            else:
                require(len(owners) == 2 and e['actor'] in owners, 'Release without shared ownership')
                owners.remove(e['actor'])
            receipts.append(dict(e, before=before, after=list(owners)))
            cursor += 1
        states.append({'frame': i, 'time': t, 'owners': {'box': list(owners)}})
    end_box = current_site if not owners else owners[0]
    require(len(owners) <= 1 and end_box == scene['box_end'], f'Custody goal mismatch: {end_box} != {scene["box_end"]}')
    for a in ACTORS:
        intervals = sorted(hands[a], key=lambda x: x['start_s'])
        require(all(x['end_s'] <= y['start_s'] for x, y in zip(intervals, intervals[1:])), f'{a}: overlapping grip actions')
    def grip(a, t, holding):
        base = offset(a, t, holding)
        for op in hands[a]:
            if not op['start_s'] <= t <= op['end_s']:
                continue
            first, contact, transfer, end = [op[k] for k in ('start_s', 'contact_s', 'transfer_s', 'end_s')]
            kind = op['kind']
            target = sites[op['site']] if kind != 'give' else studio['interaction']['shared_box']
            before_holding = kind in ('put', 'give') and a == op['actor']
            after_holding = kind == 'take' or kind == 'give' and a == op['other']
            if t < contact:
                return lerp(offset(a, first, before_holding), target, (t-first)/(contact-first))
            if t <= transfer:
                return list(target)
            return lerp(target, offset(a, end, after_holding), (t-transfer)/(end-transfer))
        return base
    actors = {}
    minimum_gap = float('inf')
    maximum_reach = 0.
    for a in ACTORS:
        keys = []
        for i in range(count+1):
            t = i/fps; p = root(a, t); angle = yaw(a, t); g = grip(a, t, a in states[i]['owners']['box'])
            delta = [x-y for x, y in zip(g, p)]; c, sn = math.cos(angle), math.sin(angle)
            local = [c*delta[0]-sn*delta[2], delta[1], sn*delta[0]+c*delta[2]]
            maximum_reach = max(maximum_reach, math.hypot(local[0], local[2]))
            keys.append({'t': t, 'position': p, 'yaw': angle, 'right_hand': local})
        actors[a] = {'size_m': [.44, 1.72, .44], 'keyframes': keys}
    require(maximum_reach <= 1.0, f'Invisible grip reach too far: {maximum_reach}')
    origin = studio['origin_blender']
    def bridge(p):
        return [origin[0]+p[0], origin[1]-p[2], origin[2]+p[1]]
    def capsule_anchor(actor, key, hand):
        # Occupancy capsules have attachment points, not anatomical arms or IK.
        p, local, angle = key['position'], key[hand], key['yaw']
        c, sn = math.cos(angle), math.sin(angle)
        return [p[0]+c*local[0]+sn*local[2], p[1]+local[1], p[2]-sn*local[0]+c*local[2]], None
    times_cache = {}
    def fast_sample(keys, t):
        # Preserve WorldOS interpolation while avoiding a full dense-list scan per frame.
        if id(keys) not in times_cache:
            times_cache[id(keys)] = [k['t'] for k in keys]
        times = times_cache[id(keys)]
        index = max(0, min(len(keys)-1, bisect.bisect_right(times, t)-1))
        return sample(keys[index:index+2], t) if index+1 < len(keys) else copy.deepcopy(keys[-1])
    compiled = compile_standin_samples(actors, states, {'box': sorted(free, key=lambda k: k['t'])},
                sample=fast_sample, hand_anchor=capsule_anchor, point_transform=bridge,
                yaw_transform=lambda value: value-math.pi, max_shared_distance=.03, max_prop_step=.2)
    rows = compiled['samples']
    for i, row in enumerate(rows):
        for j, a in enumerate(ACTORS):
            for b in ACTORS[j+1:]:
                p, q = row['actors'][a]['position'], row['actors'][b]['position']
                minimum_gap = min(minimum_gap, math.hypot(p[0]-q[0], p[1]-q[1])-.44)
    require(minimum_gap >= .2-1e-7, f'Dynamic capsule gap below .2: {minimum_gap:.4f}')
    for event in receipts:
        i = round(event['t']*fps)
        if i:
            jump = math.dist(rows[i-1]['props']['box']['position'], rows[i]['props']['box']['position'])
            require(jump <= .04, f'Ownership jump at {event["t"]}: {jump:.4f}')
    final = {'actors': {a: {'node': node_history[a], 'yaw': yaw(a, duration)} for a in ACTORS}, 'box': end_box}
    return {'samples': rows[:-1], 'endpoint': rows[-1], 'entry': copy.deepcopy(entry), 'exit': final,
            'events': receipts, 'diagnostics': {**compiled['diagnostics'], 'duration_s': duration,
                         'encoded_frames': count, 'minimum_actor_gap': minimum_gap,
                         'maximum_hidden_grip_reach': maximum_reach,
                         'grip_model': 'invisible capsule attachment, not humanoid IK'}}
