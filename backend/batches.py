"""批次权限绑定三个以内的确切候选，人工授权后串行推进。"""
import json
import math
from .domain import ExperimentSpec, digest
from .experiments import prepare_approval
from .store import identifier, now


def approve_batch(store, project, spec_ids, hashes, gpu_hours, timeout_seconds, acknowledge):
    if not acknowledge or not 1 <= len(spec_ids) <= 3 or len(set(spec_ids)) != len(spec_ids):
        raise ValueError('须明确批准 1–3 个不重复候选')
    if not isinstance(gpu_hours, (float, int)) or not math.isfinite(gpu_hours) or not 0 < gpu_hours <= 10000 or not 10 <= timeout_seconds <= 604800:
        raise ValueError('批次预算必须为有限正数')
    specs = [store.get(id, project=project) for id in spec_ids]
    models = [ExperimentSpec.model_validate(r['content']) for r in specs]
    if [r['hash'] for r in specs] != hashes:
        raise ValueError('批次规格已经变化')
    base = models[0].model_dump()
    for model in models:
        if model.phase != 'dev':
            raise ValueError('最终测试不可放入探索批次')
        for field in ('remote_id', 'dataset', 'data_manifest', 'metric', 'direction', 'seeds', 'protocol', 'min_delta'):
            if model.model_dump()[field] != base[field]:
                raise ValueError('批次只比较相同协议候选：' + field)
    prepared = [prepare_approval(store, project, r['id'], r['hash'], True)[2] for r in specs]
    batch_id = identifier('batch')
    approvals = [identifier('approval') for _ in specs]
    batch = dict(id=batch_id, members=approvals, gpu_hours=gpu_hours, timeout_seconds=timeout_seconds,
                 stagnation_limit=3, min_delta=base['min_delta'], metric=base['metric'], direction=base['direction'])
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if any(db.execute('SELECT id FROM approvals WHERE spec_id=?', (r['id'],)).fetchone() for r in specs):
            raise ValueError('候选已有独立审批，不能重新纳入批次扩大原权限')
        for id, payload, record in zip(approvals, prepared, specs):
            payload['batch'] = batch
            db.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?)',
                       (id, project, record['id'], record['hash'], json.dumps(payload), now()))
        store.event(project, 'batch.approved', batch, db=db)
    return store.put('batch', project, dict(title='受控探索批次', approvals=approvals, batch=batch,
                     spec_ids=spec_ids, approved_at=now(), status='approved', refs=[{'id': r['id'], 'version': r['version']} for r in specs]), id=batch_id)


def submit_batch(store, project, batch_id):
    from .integrations import submit
    batch = store.get(batch_id, project=project)
    if batch['kind'] != 'batch':
        raise ValueError('不是已批准批次')
    for approval in batch['content']['approvals']:
        submit(store, approval, prepare_only=True)
    result = submit(store, batch['content']['approvals'][0])
    store.event(project, 'batch.submitted', {'id': batch_id, 'status': result['status']})
    return {'id': batch_id, 'status': result['status'], 'approvals': batch['content']['approvals']}


def cancel_batch(store, project, batch_id):
    from .integrations import sync
    batch = store.get(batch_id, project=project)
    results = []
    for approval in reversed(batch['content']['approvals']):
        results.append(sync(store, approval, cancel=True))
    return {'id': batch_id, 'cancel_requested': True}
