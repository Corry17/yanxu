"""远端固定入口，仅用标准库。审批与代码快照固定后才接受运行。"""
from __future__ import annotations
import argparse
import ctypes
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
from importlib import metadata
import subprocess
import sys
import time

TERMINAL = {'done', 'failed', 'cancelled', 'blocked', 'interrupted'}
TRANSITIONS = {
    'approved': {'queued', 'cancelled'},
    'queued': {'running', 'blocked', 'cancelled', 'interrupted'},
    'running': {'done', 'blocked', 'failed', 'cancelled', 'interrupted'},
}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as src:
        for block in iter(lambda: src.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def local(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or relative.startswith('/'):
        raise ValueError('非法路径')
    path = root
    for part in relative.split('/'):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', part) or part in ('.', '..') or part.startswith('.'):
            raise ValueError('路径不在授权目录')
        path /= part
        if path.is_symlink():
            raise ValueError('不接受符号链接')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('路径越界')
    return path


def write(path, data):
    tmp = path.with_suffix('.pending')
    with tmp.open('w') as out:
        json.dump(data, out, ensure_ascii=False, allow_nan=False)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)


def identity(pid):
    try:
        # Linux starttime 避免 PID 复用；非 Linux 不启动真实训练。
        start = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + start
    except (OSError, IndexError):
        return None


def state(task):
    return json.loads((task / 'state.json').read_text())


def update(task, **fields):
    with (task / 'state.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = state(task)
        target = fields.get('status', value['status'])
        if target != value['status'] and target not in TRANSITIONS.get(value['status'], set()):
            raise ValueError('非法状态跳转或终态改写')
        value.update(fields, updated=time.time())
        write(task / 'state.json', value)
        with (task / 'events.jsonl').open('a') as out:
            out.write(json.dumps(fields | {'time': time.time()}, ensure_ascii=False) + '\n')
        return value


def batch_directory(root, batch):
    if not re.fullmatch(r'batch-[a-f0-9]{16}', batch['id']):
        raise ValueError('非法批次 ID')
    return local(root, batch['id'])


def batch_authorize(root, batch, id):
    members = batch['members']
    if not 1 <= len(members) <= 3 or len(set(members)) != len(members) or id not in members:
        raise ValueError('批次只接受明确批准的 1–3 个候选')
    if any(not re.fullmatch(r'approval-[a-f0-9]{16}', m) for m in members):
        raise ValueError('非法批次成员')
    path = batch_directory(root, batch)
    path.mkdir(exist_ok=True)
    with (path / 'ledger.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        contract = path / 'contract.json'
        if contract.exists():
            if canonical(json.loads(contract.read_text())) != canonical(batch):
                raise ValueError('批次授权不得改变')
        else:
            write(contract, batch)
            write(path / 'ledger.json', dict(completed=[], active=None, halted=False, reason='',
                                             used_seconds=0, used_gpu_hours=0, best=None, stagnant=0))


def batch_start(root, payload, id):
    batch = payload.get('batch')
    if not batch:
        return None
    directory = batch_directory(root, batch)
    with (directory / 'ledger.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = json.loads((directory / 'ledger.json').read_text())
        remaining = [m for m in batch['members'] if m not in ledger['completed']]
        if ledger['halted'] or ledger['active'] or not remaining or remaining[0] != id:
            raise ValueError('批次已停机、存在未核对任务，或试图跳过批准顺序')
        seconds = min(batch['timeout_seconds'] - ledger['used_seconds'],
                      (batch['gpu_hours'] - ledger['used_gpu_hours']) * 3600 / len(payload['spec']['gpu_ids']))
        if seconds <= 0:
            raise ValueError('批次累计预算耗尽，重启不会重置')
        ledger['active'] = id
        write(directory / 'ledger.json', ledger)
        return seconds


def batch_finish(root, payload, id, duration, score=None, error=None):
    batch = payload.get('batch')
    if not batch:
        return None
    directory = batch_directory(root, batch)
    with (directory / 'ledger.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = json.loads((directory / 'ledger.json').read_text())
        if id in ledger['completed'] or ledger['active'] != id:
            return None
        ledger['active'] = None
        ledger['completed'].append(id)
        ledger['used_seconds'] += duration
        ledger['used_gpu_hours'] += duration * len(payload['spec']['gpu_ids']) / 3600
        reason = error
        if score is not None and not reason:
            best = ledger['best']
            gain = None if best is None else (score - best) * (1 if batch['direction'] == 'max' else -1)
            improved = best is None or (gain > 0 and gain >= batch['min_delta'])
            ledger['stagnant'] = 0 if improved else ledger['stagnant'] + 1
            if improved:
                ledger['best'] = score
                if best is not None and len(payload['spec']['seeds']) < 3:
                    reason = '候选提升但尚未完成三 seed 复现，等待人工确认'
            if ledger['stagnant'] >= batch['stagnation_limit']:
                reason = '连续候选未超噪声地板，停滞熔断'
        if ledger['used_seconds'] >= batch['timeout_seconds'] or ledger['used_gpu_hours'] >= batch['gpu_hours']:
            reason = reason or '批次累计资源预算耗尽'
        ledger['halted'] = bool(reason)
        ledger['reason'] = reason or ''
        write(directory / 'ledger.json', ledger)
        remaining = [m for m in batch['members'] if m not in ledger['completed']]
        return remaining[0] if remaining and not reason else None


def authorize(root, id, payload):
    if canonical(payload['spec']) != payload['spec_hash'] or payload.get('scope') != 'exact-spec':
        raise ValueError('审批规格不一致')
    if payload.get('max_attempts') != 1:
        raise ValueError('首版失败后须重新人工归因审批，不自动重试')
    spec = payload['spec']
    if not (10 <= spec['timeout_seconds'] <= 604800 and 0 < spec['gpu_hours'] <= 10000):
        raise ValueError('缺少有效资源预算')
    if len(spec['seeds']) != len(set(spec['seeds'])) or not spec['seeds'] or len(spec['seeds']) > 8:
        raise ValueError('非法种子集合')
    if payload.get('batch'):
        batch_authorize(root, payload['batch'], id)
    task = local(root, id)
    task.mkdir(exist_ok=True)
    with (task / 'approval.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = task / 'approval.json'
        if path.exists():
            if canonical(json.loads(path.read_text())) != canonical(payload):
                raise ValueError('同一审批 ID 不得更改内容')
        else:
            write(path, payload)
            write(task / 'state.json', {'status': 'approved', 'created': time.time(), 'id': id,
                                       'spec_hash': payload['spec_hash'], 'used_seconds': 0})
    return state(task)


def submit(root, id):
    task = local(root, id)
    with (task / 'approval.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = state(task)
        if current['status'] != 'approved':
            return current
        if sys.platform != 'linux':
            raise ValueError('远程 runner 仅在 Linux 启动真实训练')
        payload = json.loads((task / 'approval.json').read_text())
        if payload.get('batch'):
            for member in payload['batch']['members']:
                member_task = local(root, member)
                if not (member_task / 'approval.json').is_file() or not (member_task / 'code').is_dir():
                    raise ValueError('整个批准批次必须先完整上传再启动')
        update(task, status='queued')
        with (task / 'supervisor.log').open('ab') as out:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(root), 'worker', id],
                                       stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
        return update(task, supervisor=process.pid, supervisor_start=identity(process.pid))


def command(spec, stage, output, code, seed, checkpoint=None):
    entry = local(code, spec['smoke_entry'] if stage == 'smoke' else spec['train_entry'])
    if entry.suffix != '.py' or not entry.is_file():
        raise ValueError('缺少已批准的 Python 入口')
    cmd = [sys.executable, '-u', str(entry)]
    for key, value in sorted(spec['parameters'].items()):
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', key) or key in {'seed', 'output-dir', 'split', 'checkpoint', 'device'}:
            raise ValueError('非法/保留参数')
        cmd.extend(['--' + key, str(value)])
    cmd.extend(['--seed', str(seed), '--output-dir', str(output), '--split', 'test' if spec['phase'] == 'final' else 'val'])
    if checkpoint:
        cmd.extend(['--checkpoint', str(checkpoint)])
    return cmd


def child_guard():
    # 监督器意外死亡时终止其直接子进程；不把 venv 宣称为恶意代码沙箱。
    ctypes.CDLL(None).prctl(1, signal.SIGKILL)
    if os.getppid() == 1:
        os._exit(1)


def execute(task, cmd, cwd, log, deadline, gpu_ids):
    if (task / 'cancel').exists() or time.monotonic() >= deadline:
        raise ValueError('运行前发现取消请求或预算已耗尽')
    approved = json.loads((task / 'approval.json').read_text())
    env = {key: value for key, value in os.environ.items() if not any(word in key.upper() for word in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY', 'SSH_AUTH_SOCK'))}
    env.update(CUDA_VISIBLE_DEVICES=','.join(map(str, gpu_ids)), PYTHONUNBUFFERED='1',
               RESEARCH_DATASET_ROOT=approved['remote']['dataset_root'])
    with log.open('xb') as out:
        process = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT,
                                   start_new_session=True, preexec_fn=child_guard)
        while process.poll() is None:
            if (task / 'cancel').exists() or time.monotonic() >= deadline or log.stat().st_size > 8 * 1024 * 1024:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise ValueError('人工取消或运行/日志预算耗尽')
            time.sleep(0.25)
        return process.returncode


def objects(path):
    rows = []
    for line in path.read_text(errors='replace').splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except ValueError:
            pass
    return rows


def environment(root):
    executable = shutil.which('nvidia-smi')
    gpus = []
    if executable:
        result = subprocess.run([executable, '--query-gpu=index,name,driver_version,memory.total', '--format=csv,noheader,nounits'],
                                capture_output=True, text=True, timeout=10, check=False)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                fields = [part.strip() for part in line.split(',')]
                if len(fields) == 4 and fields[0].isdigit():
                    gpus.append({'id': int(fields[0]), 'name': fields[1], 'driver': fields[2], 'memory_mib': fields[3]})
    packages = sorted((d.metadata.get('Name', ''), d.version) for d in metadata.distributions())
    return {'python': sys.version, 'executable': sys.executable, 'platform': sys.platform,
            'free_bytes': shutil.disk_usage(root).free, 'gpus': gpus, 'packages': packages,
            'runner': sha(Path(__file__))}


def worker(root, id):
    task = local(root, id)
    with (task / 'approval.lock').open('a') as ready:
        fcntl.flock(ready, fcntl.LOCK_EX)
        if state(task)['status'] != 'queued':
            return state(task)
    next_member = None
    payload = json.loads((task / 'approval.json').read_text())
    # 同一工作目录串行消费，SSH 断开不影响队列；不抢占其他项目进程。
    with (root / 'execution.lock').open('a') as queue:
        fcntl.flock(queue, fcntl.LOCK_EX)
        if state(task)['status'] != 'queued':
            return state(task)
        start = time.monotonic()
        try:
            batch_limit = batch_start(root, payload, id)
            if (task / 'cancel').exists():
                raise ValueError('用户已取消本任务')
            spec = payload['spec']
            if canonical(spec) != payload['spec_hash']:
                raise ValueError('审批 hash 不一致')
            env = environment(root)
            write(task / 'environment.json', env)
            if env['free_bytes'] < 100 * 1024 * 1024:
                raise ValueError('远端剩余磁盘不足 100 MiB，拒绝训练')
            if not set(spec['gpu_ids']).issubset({g['id'] for g in env['gpus']}):
                raise ValueError('预注册 GPU 不可用，请核对 NVIDIA 驱动和设备分配')
            code = task / 'code'
            for name, entry in payload['snapshot']['files'].items():
                if sha(local(code, name)) != entry['sha256']:
                    raise ValueError('代码快照已改变')
            data = Path(payload['remote']['dataset_root'])
            for relative, expected in spec['data_manifest'].items():
                if sha(local(data, relative)) != expected:
                    raise ValueError('数据版本不一致')
            limit = min(spec['timeout_seconds'], spec['gpu_hours'] * 3600 / len(spec['gpu_ids']))
            deadline = start + min(limit, batch_limit if batch_limit is not None else limit)
            scores = []
            selections = {}
            if spec['phase'] == 'final':
                selections = payload.get('frozen_selections', {})
                if set(selections) != {str(s) for s in spec['seeds']}:
                    raise ValueError('最终评测缺少审批时冻结的 checkpoint 集合')
            update(task, status='running', stage='preflight', started=time.time(), python=sys.version,
                   isolation=payload['remote']['isolation'])
            for seed in spec['seeds']:
                output = local(task, f'outputs/seed-{seed}')
                output.mkdir(parents=True, exist_ok=True)
                if spec['phase'] == 'dev':
                    update(task, stage='smoke', seed=seed)
                    log = task / f'smoke-{seed}.jsonl'
                    rc = execute(task, command(spec, 'smoke', output, code, seed), code, log, deadline, spec['gpu_ids'])
                    gates = {r.get('gate'): r.get('passed') for r in objects(log) if r.get('type') == 'smoke'}
                    if any(r.get('split') == 'test' for r in objects(log)):
                        raise ValueError('smoke 不得接触测试集指标')
                    if rc or any(gates.get(gate) is not True for gate in ('shape', 'learn', 'repeat')):
                        raise ValueError('smoke 未通过，拒绝长训')
                checkpoint = None
                if spec['phase'] == 'final':
                    parent = local(root, payload['parent_approval'])
                    selection = selections[str(seed)]
                    if state(parent)['status'] != 'done':
                        raise ValueError('开发运行尚未完成')
                    checkpoint = local(parent, selection['path'])
                    if sha(checkpoint) != selection['sha256']:
                        raise ValueError('冻结 checkpoint 已变化')
                update(task, stage='final-eval' if checkpoint else 'train', seed=seed)
                log = task / f'run-{seed}.jsonl'
                rc = execute(task, command(spec, 'train', output, code, seed, checkpoint), code, log, deadline, spec['gpu_ids'])
                if rc:
                    raise ValueError(f'子进程异常 {rc}，不是方法无效')
                rows = objects(log)
                if not any(r.get('type') == 'health' and r.get('healthy') is True for r in rows):
                    raise ValueError('缺少健康度证据，暂停后续任务')
                if any(r.get('type') == 'health' and r.get('healthy') is False for r in rows):
                    raise ValueError('健康度红线，暂停后续任务')
                if spec['phase'] == 'dev':
                    if any(r.get('split') == 'test' for r in rows):
                        raise ValueError('协议违规：开发任务访问测试指标')
                    choices = [r for r in rows if r.get('type') == 'selection']
                    values = [r for r in rows if r.get('type') == 'metric' and r.get('split') == 'val'
                              and r.get('metric') == spec['metric'] and r.get('seed', 42) == seed]
                    if len(choices) != 1 or not values or any(not math.isfinite(float(r['value'])) for r in values):
                        raise ValueError('必须恰好一个验证集选模记录')
                    best = (max if spec['direction'] == 'max' else min)(values, key=lambda r: float(r['value']))
                    if choices[0].get('step') != best.get('step') or not math.isfinite(float(best['value'])):
                        raise ValueError('checkpoint 选模与验证曲线不一致')
                    scores.append(float(best['value']))
                    checkpoint = local(output, choices[0]['checkpoint'])
                    write(task / f'selection-{seed}.json', {'path': str(checkpoint.relative_to(task)),
                          'sha256': sha(checkpoint), 'step': best['step'], 'value': best['value']})
                else:
                    values = [r for r in rows if r.get('type') == 'metric' and r.get('split') == 'test'
                              and r.get('metric') == spec['metric'] and r.get('seed', 42) == seed]
                    if len(values) != 1 or not math.isfinite(float(values[0]['value'])):
                        raise ValueError('最终评测每 seed 必须恰好一个有限目标指标，禁止择优')
            duration = time.monotonic() - start
            update(task, status='done', stage='awaiting-verifier', used_seconds=duration)
            next_member = batch_finish(root, payload, id, duration, sum(scores) / len(scores) if scores else None)
        except Exception as exc:
            duration = time.monotonic() - start
            if state(task)['status'] not in TERMINAL:
                update(task, status='cancelled' if (task / 'cancel').exists() else 'blocked',
                       error=str(exc), used_seconds=duration)
            batch_finish(root, payload, id, duration, error=str(exc))
    if next_member:
        submit(root, next_member)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('action', choices=['authorize', 'submit', 'status', 'cancel', 'worker', 'doctor'])
    parser.add_argument('id')
    args = parser.parse_args()
    if not re.fullmatch(r'approval-[a-f0-9]{16}', args.id):
        raise ValueError('非法审批 ID')
    root = args.root.resolve()
    if args.action == 'doctor':
        result = environment(root) | {'root': str(root)}
    elif args.action == 'authorize':
        raw = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('审批超限')
        result = authorize(root, args.id, json.loads(raw))
    elif args.action == 'submit':
        result = submit(root, args.id)
    elif args.action == 'worker':
        return worker(root, args.id)
    else:
        task = local(root, args.id)
        with (task / 'approval.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = state(task)
        if args.action == 'cancel':
            (task / 'cancel').touch(exist_ok=True)
            result = result | {'cancel_requested': True}
        elif result['status'] in ('running', 'queued') and (not result.get('supervisor_start') or result.get('supervisor_start') != identity(result.get('supervisor'))):
            result = update(task, status='interrupted', error='监督器身份已失效；禁止自动重训，请核对原任务')
        payload = json.loads((task / 'approval.json').read_text())
        if payload.get('batch'):
            ledger = batch_directory(root, payload['batch']) / 'ledger.json'
            result['batch'] = json.loads(ledger.read_text())
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        sys.exit(1)
