"""指标由原始日志重算；运行失败与科学结论保持分离。"""
from __future__ import annotations
from collections import defaultdict
import json
import math
import re
import statistics
from .domain import ExperimentSpec, digest
from .store import now, identifier, ROOT, safe_path
import hashlib


def parse_log(text: str):
    if len(text.encode()) > 8 * 1024 * 1024:
        raise ValueError('日志超过 8 MiB，请按运行拆分')
    metrics, health, smoke, issues = [], [], {}, []
    final = False
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if re.search(r'\b(test|holdout)\b|测试集', line, re.I):
            final = True
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get('type') == 'metric':
            try:
                value = float(row['value'])
                if not math.isfinite(value) or row['split'] not in ('train', 'val', 'test'):
                    raise ValueError()
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', row['metric']):
                    raise ValueError()
                metrics.append(dict(metric=row['metric'], value=value, split=row['split'],
                                    step=int(row.get('step', 0)), seed=int(row.get('seed', 42)), line=line_no))
                final |= row['split'] == 'test'
            except (KeyError, TypeError, ValueError, OverflowError):
                issues.append(f'第 {line_no} 行指标不合法')
        if row.get('type') == 'health':
            if type(row.get('healthy')) is bool:
                health.append(row['healthy'])
            else:
                issues.append(f'第 {line_no} 行健康度字段无效')
        if row.get('type') == 'smoke' and row.get('gate') in ('shape', 'learn', 'repeat'):
            if type(row.get('passed')) is bool:
                smoke[row['gate']] = row['passed']
    if not metrics:
        issues.append('未找到结构化指标；请使用 JSONL type=metric/metric/value/split/step/seed')
    return dict(metrics=metrics, health=health, smoke=smoke, issues=issues,
                visibility='final' if final else 'dev', parser='jsonl-v1')


def verify_log(text, spec: ExperimentSpec | None = None, returncode=0):
    parsed = parse_log(text)
    problems = list(parsed['issues'])
    if spec and spec.phase == 'dev' and parsed['visibility'] == 'final':
        verdict = 'PROTOCOL_VIOLATION'
        problems.append('开发日志接触了测试集，优先于健康度与指标裁决')
    elif returncode != 0:
        verdict = 'UNHEALTHY'
        problems.append(f'子进程退出码 {returncode}，不能作为效果负结论')
    elif any(value is False for value in parsed['health']):
        verdict = 'UNHEALTHY'
        problems.append('训练脚本报告健康度异常')
    elif not parsed['health'] or not parsed['metrics'] or problems:
        verdict = 'INCONCLUSIVE'
        if not parsed['health']:
            problems.append('缺少健康度证据')
    else:
        verdict = 'INCONCLUSIVE'
        if spec:
            split = 'test' if spec.phase == 'final' else 'val'
            if spec.phase == 'dev' and parsed['visibility'] == 'final':
                verdict = 'PROTOCOL_VIOLATION'
                problems.append('开发日志接触了测试集')
            else:
                by_seed = defaultdict(list)
                for metric in parsed['metrics']:
                    if metric['metric'] == spec.metric and metric['split'] == split:
                        by_seed[metric['seed']].append(metric['value'])
                if set(by_seed) != set(spec.seeds):
                    problems.append('种子或目标指标不完整')
                else:
                    if spec.phase == 'final' and any(len(v) != 1 for v in by_seed.values()):
                        verdict = 'PROTOCOL_VIOLATION'
                        problems.append('最终评测每个 seed 只能有一个目标指标，禁止择优')
                    else:
                        best = [(max if spec.direction == 'max' else min)(by_seed[s]) for s in spec.seeds]
                        score = statistics.mean(best)
                        passed = score >= spec.threshold if spec.direction == 'max' else score <= spec.threshold
                        verdict = 'PASS' if passed else 'FAIL'
        else:
            problems.append('导入日志未绑定预注册判据，只描述观察，不裁决方法有效性')
    groups = defaultdict(list)
    for row in parsed['metrics']:
        groups[(row['split'], row['metric'], row['seed'])].append(row)
    summaries = []
    for (split, metric, seed), rows in groups.items():
        last = max(rows, key=lambda row: (row['step'], row['line']))
        summaries.append(dict(split=split, metric=metric, seed=seed, value=last['value'], line=last['line']))
    return parsed | dict(verdict=verdict, problems=problems, summaries=summaries,
                         note='单 seed 仅为初步观察；表格展示各 seed 最后一个日志点，非自动选模结论。')


def prepare_approval(store, project, spec_id, expected_hash, acknowledge):
    record = store.get(spec_id, project=project)
    spec = ExperimentSpec.model_validate(record['content'])
    if record['hash'] != expected_hash or not acknowledge:
        raise ValueError('请核对并明确批准当前规格、代码及预算')
    remote = store.get(spec.remote_id, project=project)
    if not remote['content'].get('consent'):
        raise ValueError('远程部署与运行尚未授权')
    snapshot = store.get(spec.snapshot_id, project=project)
    if snapshot['kind'] != 'snapshot':
        raise ValueError('实验需要完整代码快照')
    files = snapshot['content']['files']
    if spec.train_entry not in files or spec.smoke_entry not in files:
        raise ValueError('快照中缺少训练或 smoke 入口')
    store.check_refs(project, spec.refs, dev_only=spec.phase == 'dev')
    parent_approval = None
    frozen_selections = {}
    if spec.phase == 'final':
        parent = store.get(spec.final_from, project=project)
        if parent['kind'] != 'run' or parent['content'].get('verdict') != 'PASS' or not parent['content'].get('approval_id') or parent['visibility'] != 'dev':
            raise ValueError('最终评测必须引用已核验的开发运行')
        parent_approval = parent['content']['approval_id']
        frozen_selections = parent['content'].get('selections', {})
        if set(frozen_selections) != {str(s) for s in spec.seeds}:
            raise ValueError('开发运行尚无核验过的 checkpoint 指纹集合')
        parent_spec = approved_payload(store, parent_approval)['payload']['spec']
        for field in ('snapshot_id', 'parameters', 'seeds', 'dataset', 'data_manifest', 'remote_id'):
            if parent_spec[field] != spec.model_dump()[field]:
                raise ValueError('最终评测必须保留冻结候选的 ' + field)
    payload = dict(spec=spec.model_dump(), spec_hash=record['hash'], snapshot=snapshot['content'],
                   snapshot_hash=snapshot['hash'], remote=remote['content'], remote_hash=remote['hash'],
                   approved_at=now(), scope='exact-spec', max_attempts=1,
                   spec_version=record['version'], runner_source=(ROOT / 'runner/remote.py').read_text())
    if parent_approval:
        payload['parent_approval'] = parent_approval
        payload['frozen_selections'] = frozen_selections
    return record, spec, payload


def approve(store, project, spec_id, expected_hash, acknowledge):
    record, spec, payload = prepare_approval(store, project, spec_id, expected_hash, acknowledge)
    id = identifier('approval')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT id FROM approvals WHERE spec_id=? AND spec_hash=?', (spec_id, record['hash'])).fetchone()
        if existing:
            return dict(id=existing[0], duplicate=True)
        if spec.phase == 'final':
            used = db.execute('SELECT payload FROM approvals WHERE project=?', (project,)).fetchall()
            if any(json.loads(row[0])['spec'].get('final_from') == spec.final_from for row in used):
                raise ValueError('该冻结候选已经授权过最终测试，不能通过新建规格重新测试')
        db.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?)', (id, project, spec_id, record['hash'], json.dumps(payload), now()))
        store.event(project, 'experiment.approved', {'id': id, 'spec_id': spec_id}, spec.phase, db)
    return dict(id=id, duplicate=False)


def approved_payload(store, approval_id):
    with store.connect() as db:
        row = db.execute('SELECT * FROM approvals WHERE id=?', (approval_id,)).fetchone()
    if not row:
        raise ValueError('没有有效审批')
    payload = json.loads(row['payload'])
    if store.get(row['spec_id'])['hash'] != row['spec_hash']:
        raise ValueError('规格变更，原审批失效')
    spec = payload['spec']
    if store.get(spec['snapshot_id'])['hash'] != payload['snapshot_hash'] or store.get(spec['remote_id'])['hash'] != payload['remote_hash']:
        raise ValueError('代码或远程配置已改变，请重新审批')
    return dict(row) | {'payload': payload}


def compare_runs(store, project, ids, include_final=False):
    groups = {}
    excluded = []
    if not 1 <= len(ids) <= 30 or len(set(ids)) != len(ids):
        raise ValueError('对照需要 1–30 个不同运行')
    for id in ids:
        record = store.get(id, project=project)
        content = record['content']
        if record['kind'] != 'run':
            raise ValueError('只能比较运行记录')
        if record['visibility'] == 'final' and not include_final:
            raise ValueError('最终测试对照必须显式选择最终报告范围')
        if not content.get('spec_id') or not content.get('blob'):
            excluded.append({'id': id, 'title': content['title'], 'reason': '未绑定预注册协议，只能阅读原始日志，不可直接比较'})
            continue
        raw = safe_path(store.root, content['blob'], True).read_bytes()
        if hashlib.sha256(raw).hexdigest() != content['log_hash']:
            raise ValueError('原始日志已变化')
        refs = content.get('refs', [])
        ref = next((r for r in refs if r['id'] == content['spec_id']), None)
        spec = ExperimentSpec.model_validate(store.get(content['spec_id'], ref['version'] if ref else None, project)['content'])
        contract = {k: spec.model_dump()[k] for k in ('dataset', 'data_manifest', 'metric', 'direction', 'seeds', 'protocol', 'phase')}
        group_id = digest(contract)
        group = groups.setdefault(group_id, {'id': group_id, 'protocol': contract, 'runs': []})
        metrics = parse_log(raw.decode())['metrics']
        values = []
        if content['status'] == 'done' and content['verdict'] in ('PASS', 'FAIL'):
            split = 'test' if spec.phase == 'final' else 'val'
            for seed in spec.seeds:
                candidates = [m for m in metrics if m['seed'] == seed and m['metric'] == spec.metric and m['split'] == split]
                if candidates:
                    values.append((max if spec.direction == 'max' else min)(m['value'] for m in candidates))
        group['runs'].append({'id': id, 'title': content['title'], 'verdict': content['verdict'],
                              'valid_seeds': len(values), 'planned_seeds': len(spec.seeds),
                              'mean': statistics.mean(values) if values else None,
                              'std': statistics.stdev(values) if len(values) > 1 else None,
                              'note': '样本标准差；未做显著性检验' if len(values) > 1 else '单 seed 或证据不足，不宣称稳定提升'})
    return {'groups': list(groups.values()), 'excluded': excluded,
            'note': '仅同协议组可对照，不跨组排名；失败与缺失运行保留。最终测试表不用于选择下一轮方案。'}
