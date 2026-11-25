"""Resumable, recorded JSON role jobs; synthetic production data only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def run_json(folder, job_id, prompt, schema, config, images=()):
    job = Path(folder) / 'jobs' / job_id
    signature = digest({'prompt': prompt, 'schema': schema, 'model': config['model'],
                        'images': [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in images]})
    if (job / 'receipt.json').exists():
        receipt = json.loads((job / 'receipt.json').read_text())
        if receipt['input_sha256'] != signature:
            raise ValueError(f'Inputs changed for completed job {job_id}; use a new revision ID')
        if receipt['exit_code'] == 0:
            return json.loads((job / 'result.json').read_text())
    job.mkdir(parents=True, exist_ok=True)
    (job / 'prompt.txt').write_text(prompt)
    (job / 'schema.json').write_text(json.dumps(schema, ensure_ascii=False))
    result_path = job / 'result.json'
    args = [config['codex_bin'], 'exec', '--ignore-user-config', '--json',
            '--skip-git-repo-check', '--sandbox', 'read-only', '-C', str(job),
            '-c', 'model=' + config['model'], '-c', 'model_reasoning_effort=' + config['reasoning_effort'],
            '-c', 'features.multi_agent=false', '--output-schema', str(job / 'schema.json'),
            '--output-last-message', str(result_path)]
    for path in images:
        args += ['--image', str(path)]
    args += ['-']
    started = time.monotonic()
    env = {k: v for k, v in os.environ.items() if k in {
        'PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'TMPDIR', 'LANG', 'LC_ALL', 'TERM'}}
    with (job / 'events.jsonl').open('wb') as events, (job / 'stderr.log').open('wb') as errors:
        process = subprocess.run(args, input=prompt.encode(), stdout=events, stderr=errors,
                                 env=env, timeout=1200)
    events = [json.loads(line) for line in (job / 'events.jsonl').read_text().splitlines() if line.strip()]
    usage = next((e.get('usage') for e in reversed(events) if e.get('type') == 'turn.completed'), None)
    receipt = {'job': job_id, 'model': config['model'], 'input_sha256': signature,
               'prompt_characters': len(prompt), 'exit_code': process.returncode,
               'seconds': time.monotonic() - started, 'usage': usage,
               'transport': 'authenticated Codex role job; not native WorldOS runtime'}
    (job / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)
    if process.returncode or not result_path.exists():
        raise RuntimeError(f'Role job failed: {job}; see stderr.log')
    return json.loads(result_path.read_text())


def object_schema(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


def array_schema(items, minimum=0, maximum=None):
    result = {'type': 'array', 'items': items, 'minItems': minimum}
    if maximum is not None:
        result['maxItems'] = maximum
    return result


STRING = {'type': 'string'}
NUMBER = {'type': 'number'}
