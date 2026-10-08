"""合成执行器验证控制协议，不连接 SSH 或消耗 GPU。"""
import json
from pathlib import Path
import pytest
from backend.store import Store
from backend.domain import Project
from backend.batches import approve_batch
from backend.experiments import approve, approved_payload, verify_log
from runner import remote
from test_workbench import setup_spec


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, 'environment', lambda root: {'gpus': [{'id': 0}], 'free_bytes': 10**9, 'test_stub': True})
    store = Store(tmp_path / 'local')
    project = 'p'
    store.put('project', project, Project(title='控制协议测试').model_dump(), id=project)
    root = tmp_path / 'remote'
    root.mkdir()
    return store, project, root


def batch_env(env, n=3):
    store, project, root = env
    first, spec = setup_spec(store, project)
    records = [first] + [store.put('spec', project, spec.model_dump() | {'title': '候选' + str(i), 'parameters': {'variant': i}}) for i in range(1, n)]
    batch = approve_batch(store, project, [r['id'] for r in records], [r['hash'] for r in records], 1, 100, True)
    members = batch['content']['approvals']
    payloads = [approved_payload(store, id)['payload'] for id in members]
    for id, payload in zip(members, payloads):
        remote.authorize(root, id, payload)
    return batch, members, payloads


def test_batch_atomic_validation(env):
    store, project, root = env
    first, spec = setup_spec(store, project)
    second = store.put('spec', project, spec.model_dump() | {'protocol': '另一数据协议'})
    with pytest.raises(ValueError):
        approve_batch(store, project, [first['id'], second['id']], [first['hash'], second['hash']], 1, 100, True)
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0] == 0


def test_batch_budget_is_persistent_and_ordered(env):
    batch, ids, payloads = batch_env(env)
    root = env[2]
    with pytest.raises(ValueError):
        remote.batch_start(root, payloads[1], ids[1])
    assert remote.batch_start(root, payloads[0], ids[0]) == 100
    with pytest.raises(ValueError):
        remote.batch_start(root, payloads[0], ids[0])
    assert remote.batch_finish(root, payloads[0], ids[0], 30, score=.5) == ids[1]
    # 再次授权/重启不清空累计预算。
    remote.authorize(root, ids[0], payloads[0])
    assert remote.batch_start(root, payloads[1], ids[1]) == 70
    remote.batch_finish(root, payloads[1], ids[1], 71, score=.6)
    with pytest.raises(ValueError):
        remote.batch_start(root, payloads[2], ids[2])


def test_batch_failure_and_unconfirmed_improvement_stop(env):
    _, ids, payloads = batch_env(env)
    root = env[2]
    remote.batch_start(root, payloads[0], ids[0])
    remote.batch_finish(root, payloads[0], ids[0], 1, score=.5)
    remote.batch_start(root, payloads[1], ids[1])
    assert remote.batch_finish(root, payloads[1], ids[1], 1, score=.4) is None
    ledger = json.loads((root / payloads[0]['batch']['id'] / 'ledger.json').read_text())
    assert ledger['halted'] and '三 seed' in ledger['reason']
    with pytest.raises(ValueError):
        remote.batch_start(root, payloads[2], ids[2])


def test_unknown_failure_does_not_clear_active_batch(env):
    _, ids, payloads = batch_env(env)
    root = env[2]
    remote.batch_start(root, payloads[0], ids[0])
    remote.batch_finish(root, payloads[1], ids[1], 1, error='顺序错误')
    ledger = json.loads((root / payloads[0]['batch']['id'] / 'ledger.json').read_text())
    assert ledger['active'] == ids[0]


def prepare_task(env):
    store, project, root = env
    record, spec = setup_spec(store, project)
    id = approve(store, project, record['id'], record['hash'], True)['id']
    payload = approved_payload(store, id)['payload']
    data = root / 'dataset'
    data.mkdir()
    for filename in payload['spec']['data_manifest']:
        (data / filename).write_text('frozen data')
        payload['spec']['data_manifest'][filename] = remote.sha(data / filename)
    payload['spec_hash'] = remote.canonical(payload['spec'])
    payload['remote']['dataset_root'] = str(data)
    remote.authorize(root, id, payload)
    task = root / id
    (task / 'code').mkdir()
    for name, entry in payload['snapshot']['files'].items():
        (task / 'code' / name).write_text(entry['text'])
    remote.update(task, status='queued')
    return id, payload, task


def stub_execute(task, cmd, cwd, log, deadline, gpu_ids):
    seed = int(cmd[cmd.index('--seed') + 1])
    if 'smoke' in log.name:
        rows = [{'type': 'smoke', 'gate': g, 'passed': True} for g in ('shape', 'learn', 'repeat')]
    else:
        output = Path(cmd[cmd.index('--output-dir') + 1])
        (output / 'checkpoint.bin').write_bytes(b'frozen weights')
        rows = [{'type': 'health', 'healthy': True},
                {'type': 'metric', 'metric': 'loss', 'value': .4, 'split': 'val', 'seed': seed, 'step': 1},
                {'type': 'selection', 'step': 1, 'checkpoint': 'checkpoint.bin'}]
    log.write_text('\n'.join(json.dumps(r) for r in rows))
    return 0


def test_full_stub_run_freezes_checkpoint_and_is_not_repeated(env, monkeypatch):
    id, payload, task = prepare_task(env)
    calls = []
    def fake(*args):
        calls.append(args[3].name)
        return stub_execute(*args)
    monkeypatch.setattr(remote, 'execute', fake)
    remote.worker(env[2], id)
    assert remote.state(task)['status'] == 'done'
    selection = json.loads((task / 'selection-42.json').read_text())
    assert selection['sha256'] == remote.sha(task / selection['path'])
    remote.worker(env[2], id)
    assert len(calls) == 2


def test_smoke_failure_refuses_training(env, monkeypatch):
    id, payload, task = prepare_task(env)
    calls = []
    def fail(task, cmd, cwd, log, deadline, gpu_ids):
        calls.append(log.name)
        log.write_text('{"type":"smoke","gate":"shape","passed":false}')
        return 1
    monkeypatch.setattr(remote, 'execute', fail)
    remote.worker(env[2], id)
    assert remote.state(task)['status'] == 'blocked'
    assert calls == ['smoke-42.jsonl']


def test_changed_code_refuses_execution(env, monkeypatch):
    id, payload, task = prepare_task(env)
    (task / 'code/train.py').write_text('different code')
    monkeypatch.setattr(remote, 'execute', lambda *a: pytest.fail('不应启动'))
    remote.worker(env[2], id)
    assert remote.state(task)['status'] == 'blocked'
    assert '快照' in remote.state(task)['error']


def test_final_requires_approval_time_checkpoint_hash(env, monkeypatch):
    id, payload, task = prepare_task(env)
    monkeypatch.setattr(remote, 'execute', stub_execute)
    remote.worker(env[2], id)
    selection = json.loads((task / 'selection-42.json').read_text())
    final_id = 'approval-' + 'f' * 16
    final = json.loads(json.dumps(payload))
    final['spec']['phase'] = 'final'
    final['spec_hash'] = remote.canonical(final['spec'])
    final['parent_approval'] = id
    final['frozen_selections'] = {'42': selection}
    remote.authorize(env[2], final_id, final)
    final_task = env[2] / final_id
    (final_task / 'code').mkdir()
    for name, entry in payload['snapshot']['files'].items():
        (final_task / 'code' / name).write_text(entry['text'])
    (task / selection['path']).write_bytes(b'altered checkpoint')
    remote.update(final_task, status='queued')
    monkeypatch.setattr(remote, 'execute', lambda *a: pytest.fail('不应评测变更的 checkpoint'))
    remote.worker(env[2], final_id)
    assert remote.state(final_task)['status'] == 'blocked'
    assert 'checkpoint' in remote.state(final_task)['error']


def test_final_metrics_cannot_be_selected_by_best(env):
    _, spec = setup_spec(env[0], env[1])
    final = spec.model_copy(update={'phase': 'final', 'final_from': 'r'})
    text = '\n'.join(json.dumps(r) for r in [{'type': 'health', 'healthy': True},
        {'type': 'metric', 'metric': 'loss', 'split': 'test', 'seed': 42, 'value': .4},
        {'type': 'metric', 'metric': 'loss', 'split': 'test', 'seed': 42, 'value': .2}])
    assert verify_log(text, final)['verdict'] == 'PROTOCOL_VIOLATION'


def test_budget_checked_before_spawning(env, monkeypatch):
    id, payload, task = prepare_task(env)
    monkeypatch.setattr(remote.subprocess, 'Popen', lambda *a, **kw: pytest.fail('预算耗尽不应创建进程'))
    with pytest.raises(ValueError):
        remote.execute(task, ['not-executed'], task, task / 'log', 0, [0])


def test_explicit_state_machine_refuses_jump(env):
    id, payload, task = prepare_task(env)
    with pytest.raises(ValueError, match='状态'):
        remote.update(task, status='done')


def test_gpu_preflight_prevents_execution(env, monkeypatch):
    id, payload, task = prepare_task(env)
    monkeypatch.setattr(remote, 'environment', lambda root: {'gpus': [], 'free_bytes': 10**9})
    monkeypatch.setattr(remote, 'execute', lambda *a: pytest.fail('GPU 缺失不能训练'))
    remote.worker(env[2], id)
    assert remote.state(task)['status'] == 'blocked'
    assert 'GPU' in remote.state(task)['error']


def test_comparison_does_not_hide_failed_runs_or_mix_protocols(env):
    from backend.experiments import compare_runs
    import hashlib
    store, project, _ = env
    record, spec = setup_spec(store, project)
    different = store.put('spec', project, spec.model_dump() | {'dataset': 'v2'})
    raw = b'{"type":"health","healthy":true}\n{"type":"metric","metric":"loss","value":0.4,"split":"val","seed":42}'
    blob = store.save_blob(raw, '.jsonl')
    ids = []
    for source, verdict, status in [(record, 'PASS', 'done'), (record, 'UNHEALTHY', 'blocked'), (different, 'PASS', 'done')]:
        run = store.put('run', project, {'title': verdict, 'spec_id': source['id'], 'blob': blob,
            'log_hash': hashlib.sha256(raw).hexdigest(), 'verdict': verdict, 'status': status,
            'refs': [{'id': source['id'], 'version': source['version']}]})
        ids.append(run['id'])
    result = compare_runs(store, project, ids)
    assert len(result['groups']) == 2
    runs = [r for group in result['groups'] for r in group['runs']]
    assert len(runs) == 3
    assert next(r for r in runs if r['verdict'] == 'UNHEALTHY')['mean'] is None
    assert next(r for r in runs if r['verdict'] == 'PASS')['std'] is None
