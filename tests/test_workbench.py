from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import io
import json
import shutil
import sys
import zipfile
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.store import Store, safe_path
from backend.domain import Project, ExperimentSpec, ReportRequest, digest
from backend.demo import create_demo
from backend.experiments import verify_log, approve, approved_payload
from backend.research import planner_context, deep_read
from backend.reports import export_report, compile_report, math_svg, check_skill
from backend.orchestrator import Scheduler
from backend.literature import import_pdf, import_snapshot
from runner.remote import authorize, submit, local


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'data')


@pytest.fixture
def project(store):
    store.put('project', 'p', Project(title='真实研究项目', question='如何检验一个方法？').model_dump(), id='p')
    return 'p'


@pytest.fixture
def client(store):
    with TestClient(create_app(store, background=False)) as client:
        token = client.get('/api/session').json()['token']
        client.headers['x-research-token'] = token
        yield client


def setup_spec(store, project):
    snapshot = import_snapshot(store, project, [('train.py', b'print(1)'), ('smoke.py', b'print(1)')], '代码')
    remote = store.put('remote', project, dict(title='测试环境', alias='gpu', root='/tmp/research', python='/usr/bin/python3', dataset_root='/tmp/datasets', consent=True, isolation='protocol'))
    spec = ExperimentSpec(title='验证单变量', hypothesis='来自论文机制的假设，仅在验证集进行比较。', snapshot_id=snapshot['id'],
                          remote_id=remote['id'], train_entry='train.py', smoke_entry='smoke.py', dataset='v1',
                          data_manifest={'train.csv': 'a' * 64, 'val.csv': 'b' * 64}, metric='loss', direction='min',
                          threshold=.5, timeout_seconds=30, gpu_hours=.1, protocol='同一验证划分与选模条件')
    record = store.put('spec', project, spec.model_dump())
    return record, spec


def test_record_versions_and_stale(store, project):
    paper = store.put('paper', project, {'title': '论文'})
    note = store.put('note', project, {'title': '讲解', 'refs': [{'id': paper['id'], 'version': 1}]})
    assert not store.stale(note)
    store.put('paper', project, {'title': '修订论文'}, id=paper['id'])
    assert store.stale(note)
    assert store.get(paper['id'], 1)['content']['title'] == '论文'
    with pytest.raises(ValueError):
        store.put('paper', project, {}, id=paper['id'], expected=1)


def test_final_evidence_never_in_planner_or_index(store, project):
    r = store.put('run', project, {'title': 'UNIQUE_TEST_RESULT', 'summaries': [{'value': 99}]}, visibility='final')
    store.put('note', project, {'title': 'UNIQUE_TEST_RESULT 派生结论', 'text': '秘密'}, visibility='final')
    store.put('report', project, {'title': '报告包含测试', 'snapshot': {'text': '秘密'}}, visibility='final')
    assert 'UNIQUE_TEST_RESULT' not in json.dumps(planner_context(store, project))
    with store.connect() as db:
        assert not db.execute("SELECT * FROM search WHERE search MATCH ?", ('UNIQUE_TEST_RESULT',)).fetchall()
    with pytest.raises(ValueError):
        store.check_refs(project, [{'id': r['id'], 'version': 1}], dev_only=True)


def test_missing_health_not_success():
    log = json.dumps({'type': 'metric', 'metric': 'loss', 'value': .1, 'split': 'val'})
    assert verify_log(log)['verdict'] == 'INCONCLUSIVE'
    assert verify_log(log, returncode=2)['verdict'] == 'UNHEALTHY'
    assert verify_log('not a metric')['summaries'] == []


def test_protocol_violation_overrides_good_metric(store, project):
    _, spec = setup_spec(store, project)
    log = '\n'.join(json.dumps(r) for r in [{'type': 'health', 'healthy': True},
         {'type': 'metric', 'metric': 'loss', 'value': .1, 'split': 'val'},
         {'type': 'metric', 'metric': 'loss', 'value': .1, 'split': 'test'}])
    assert verify_log(log, spec)['verdict'] == 'PROTOCOL_VIOLATION'


def test_nonfinite_metrics_are_not_results():
    log = '{"type":"metric","metric":"auc","value":NaN,"split":"val"}'
    result = verify_log(log)
    assert not result['metrics']
    assert result['verdict'] == 'INCONCLUSIVE'


def test_approval_requires_hash_and_scope(store, project):
    record, spec = setup_spec(store, project)
    with pytest.raises(ValueError):
        approve(store, project, record['id'], 'wrong', True)
    with pytest.raises(ValueError):
        approve(store, project, record['id'], record['hash'], False)
    first = approve(store, project, record['id'], record['hash'], True)
    assert approve(store, project, record['id'], record['hash'], True)['id'] == first['id']
    store.put('spec', project, spec.model_dump() | {'threshold': .2}, id=record['id'])
    with pytest.raises(ValueError):
        approved_payload(store, first['id'])


@pytest.mark.parametrize('value', ['../secrets', '/etc/passwd', 'a/../../b', '.env', 'a\\b'])
def test_path_rejection(store, value):
    with pytest.raises(ValueError):
        safe_path(store.root, value)
    with pytest.raises(ValueError):
        local(store.root, value)


def test_symlink_rejection(store):
    (store.root / 'escape').symlink_to(store.root.parent)
    with pytest.raises(ValueError):
        safe_path(store.root, 'escape/file.txt')


def test_queue_idempotency_and_recovery(store, project):
    one = store.enqueue(project, 'submit', {'approval_id': 'same'}, key='same')
    two = store.enqueue(project, 'submit', {'approval_id': 'same'}, key='same')
    assert one['id'] == two['id']
    assert store.claim()['id'] == one['id']
    assert store.claim() is None
    store.recover()
    assert store.claim()['id'] == one['id']
    store.finish(one['id'], {'ok': True})
    assert store.claim() is None


def test_remote_duplicate_submit_never_restarts(store, project, tmp_path):
    record, spec = setup_spec(store, project)
    approval = approve(store, project, record['id'], record['hash'], True)
    payload = approved_payload(store, approval['id'])['payload']
    root = tmp_path / 'remote'
    root.mkdir()
    authorize(root, approval['id'], payload)
    task = root / approval['id']
    (task / 'state.json').write_text(json.dumps({'status': 'done', 'used_seconds': 27}))
    assert submit(root, approval['id'])['used_seconds'] == 27
    changed = dict(payload, spec_hash='0' * 64)
    with pytest.raises(ValueError):
        authorize(root, approval['id'], changed)


def test_http_guard_and_cross_project(client, store, project):
    assert client.post('/api/projects', json={'title': 'new'}, headers={'origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/projects', json={'title': 'new'}, headers={'x-research-token': ''}).status_code == 403
    assert client.get('/api/projects', headers={'host': 'evil.example'}).status_code == 403
    assert client.post('/api/projects/p/search', json={'query': 'attention'}).status_code == 400
    result = client.post('/api/projects', json={'title': '合法本地项目'})
    assert result.status_code == 200
    assert result.json()['content']['search_consent'] is False


def test_log_import_flags_test(client, project):
    raw = b'{"type":"metric","metric":"loss","value":0.3,"split":"test"}\n'
    response = client.post('/api/projects/p/log', files={'file': ('run.jsonl', raw)}, data={'protocol': 'final evaluation'})
    assert response.status_code == 200
    assert response.json()['visibility'] == 'final'
    context = client.get('/api/projects/p/planner-context').json()
    assert context['evidence'] == []


def test_abstract_cannot_be_deep_read(store, project):
    paper = store.put('paper', project, {'title': '摘要', 'access': 'abstract'})
    with pytest.raises(ValueError, match='全文'):
        deep_read(store, project, paper['id'], [1])


def test_model_and_remote_off_by_default(client, project):
    assert client.get('/api/settings/model').json()['consent'] is False
    assert client.post('/api/projects/p/propose').status_code == 400


def test_demo_marks_every_result(store):
    p = create_demo(store)
    assert p['content']['demo'] is True
    for record in store.list(p['id'], 'run'):
        assert record['content']['demo'] is True
        assert record['content']['verdict'] == 'INCONCLUSIVE'
        raw = safe_path(store.root, record['content']['blob'], True).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record['content']['log_hash']


def test_report_three_structures_and_offline_pack(store, tmp_path):
    check_skill()
    p = create_demo(store)
    reading = store.list(p['id'], 'reading')[0]
    run = store.list(p['id'], 'run')[0]
    for kind, sources in [('paper', [reading['id']]), ('experiment', [run['id']]), ('weekly', [])]:
        request = ReportRequest(kind=kind, title='教学示例报告', sources=sources, style='academic',
                                start=datetime.now(timezone.utc) - timedelta(days=1),
                                end=datetime.now(timezone.utc) + timedelta(days=1))
        record = export_report(store, p['id'], request)
        entry = safe_path(store.root, record['content']['entry'], True)
        html = entry.read_text()
        assert '教学示例' in html
        assert 'cdn.' not in html and '<script src=' not in html
        if kind == 'paper':
            assert '<svg' in html and '符号' in html and '辅助教学图' in html
        if kind == 'experiment':
            assert '协议与本轮改动' in html and 'synthetic_loss' in html
        if kind == 'weekly':
            assert '目标与本周研究问题' in html
        with zipfile.ZipFile(safe_path(store.root, record['content']['archive'], True)) as archive:
            assert not any('project.json' in n or 'research-report.json' in n for n in archive.namelist())
            assert any(n.endswith('index.html') for n in archive.namelist())
        target = tmp_path / ('moved-' + kind)
        shutil.copytree(entry.parent, target)
        assert (target / 'resources.html').is_file()


def test_final_report_requires_opt_in(store, project):
    run = store.put('run', project, {'title': 'final'}, visibility='final')
    request = ReportRequest(kind='experiment', title='test', sources=[run['id']], style='lab')
    with pytest.raises(ValueError):
        compile_report(store, project, request)


@pytest.mark.parametrize('latex', [r'\href{javascript:alert(1)}{x}', r'\require{html}', r'\includegraphics{x}', r'\def\a{\a}\a'])
def test_active_latex_refused(latex):
    with pytest.raises(ValueError):
        math_svg(latex)


def test_schedule_idempotent(store, project):
    before = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with store.connect() as db:
        db.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?)', ('s', project, 'propose', 3600, before, '{}', 1))
    scheduler = Scheduler(store)
    scheduler.schedules()
    scheduler.schedules()
    assert len(store.jobs(project)) == 1


def test_pdf_original_and_page_images(store, project):
    from PIL import Image
    image = Image.new('RGB', (300, 200), 'white')
    out = io.BytesIO()
    image.save(out, format='PDF')
    record = import_pdf(store, project, 'example.pdf', out.getvalue())
    assert record['content']['access'] == 'fulltext'
    assert len(record['content']['pages']) == 1
    assert safe_path(store.root, record['content']['pages'][0]['image'], True).exists()
    assert import_pdf(store, project, 'renamed.pdf', out.getvalue())['id'] == record['id']
