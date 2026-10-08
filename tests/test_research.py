from datetime import datetime, timedelta, timezone
import json
import socket
import pytest
from backend.store import Store
from backend.domain import Project, ReportRequest
from backend import research, literature, reports, net
from backend.demo import create_demo


@pytest.fixture
def project(tmp_path):
    store = Store(tmp_path / 'research')
    store.put('project', 'p', Project(title='研究课题', question='如何改善泛化？', search_consent=True, model_consent=True).model_dump(), id='p')
    return store


def test_recommendation_validates_sources_and_marks_abstract(project, monkeypatch):
    paper = project.put('paper', 'p', {'title': '真实元数据', 'abstract': '摘要', 'access': 'abstract'})
    monkeypatch.setattr(literature, 'search_arxiv', lambda *args: [paper])
    answers = iter([{'query': 'generalization', 'rationale': '对应研究问题'}, {'papers': [{'id': paper['id'], 'relevance': '机制相关', 'mismatch': '未取得全文'}]}])
    monkeypatch.setattr(research, 'call_model', lambda *args, **kw: next(answers))
    result = research.recommend(project, 'p')
    assert result[0]['content']['recommendation_scope'] == 'abstract'
    assert result[0]['content']['access'] == 'abstract'


def test_recommendation_rejects_fake_papers(project, monkeypatch):
    paper = project.put('paper', 'p', {'title': '元数据', 'abstract': ''})
    monkeypatch.setattr(literature, 'search_arxiv', lambda *args: [paper])
    answers = iter([{'query': 'generalization', 'rationale': '相关'}, {'papers': [{'id': 'fake', 'relevance': '声称相关', 'mismatch': ''}]}])
    monkeypatch.setattr(research, 'call_model', lambda *args, **kw: next(answers))
    with pytest.raises(ValueError, match='不存在'):
        research.recommend(project, 'p')


def test_repeated_context_does_not_spend_model_calls(project, monkeypatch):
    calls = []
    def model(*args):
        calls.append(1)
        return dict(title='缺证据', question='当前问题', observation='缺少日志', hypothesis='待补', evidence_ids=[], action='stop', next_steps=['补日志'], missing=['日志'], reason='不足以判断')
    monkeypatch.setattr(research, 'call_model', model)
    first = research.propose(project, 'p')
    second = research.propose(project, 'p')
    assert first['id'] == second['id'] and len(calls) == 1
    assert not research.planner_context(project, 'p')['evidence']


def test_code_explanation_uses_real_lines(project, monkeypatch):
    snapshot = literature.import_snapshot(project, 'p', [('train.py', b'x = 2\ny = x + 1\n')], '快照')
    monkeypatch.setattr(research, 'call_model', lambda *a, **kw: dict(title='计算流程', summary='静态解释', blocks=[dict(title='加一', start=2, end=2, explanation=['输入 x，输出 y'], formula='y=x+1')]))
    study = research.explain_code(project, 'p', snapshot['id'], 'train.py')
    assert study['content']['code'][0]['code'] == 'y = x + 1'
    assert 'L2–L2' in study['content']['code'][0]['location']
    assert study['content']['code'][0]['status'] == 'static'
    monkeypatch.setattr(research, 'call_model', lambda *a, **kw: dict(title='不存在行', summary='', blocks=[dict(title='假', start=2, end=100, explanation=[], formula='')]))
    with pytest.raises(ValueError, match='不存在'):
        research.explain_code(project, 'p', snapshot['id'], 'train.py')


def test_final_evidence_taints_derived_notes(project):
    run = project.put('run', 'p', {'title': '最终结果'}, visibility='final')
    derived = project.put('note', 'p', {'title': '派生判断', 'text': '不能进入规划', 'refs': [{'id': run['id'], 'version': 1}]})
    assert derived['visibility'] == 'final'
    assert not research.planner_context(project, 'p')['evidence']


def test_http_connection_rejects_rebound_private_ip(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(ValueError, match='禁止'):
        net.PublicHTTPS('untrusted.example').connect()


def test_historical_report_uses_version_at_cutoff(project):
    note = project.put('note', 'p', {'title': '早期观察', 'text': '最初证据', 'category': 'progress', 'refs': []})
    cutoff = datetime.now(timezone.utc)
    project.put('note', 'p', {'title': '修订观察', 'text': '后续新证据', 'category': 'progress', 'refs': []}, id=note['id'])
    request = ReportRequest(kind='weekly', title='历史周报', style='academic', start=cutoff - timedelta(hours=1), end=cutoff)
    data, records = reports.compile_report(project, 'p', request)
    assert records[0]['content']['text'] == '最初证据'
    assert records[0]['version'] == 1


def test_report_calendar_days_use_project_timezone(project):
    p = project.get('p')
    project.put('project', 'p', p['content'] | {'timezone': 'America/New_York'}, id='p')
    request = ReportRequest(kind='weekly', title='日期报告', style='academic', start_day='2026-03-08', end_day='2026-03-08')
    data, _ = reports.compile_report(project, 'p', request)
    assert '2026-03-08T00:00:00-05:00' in data['period']
    assert '2026-03-09T00:00:00-04:00' in data['period']


def test_export_revalidates_log_hash(project):
    p = create_demo(project)
    run = project.list(p['id'], 'run')[0]
    path = project.root / run['content']['blob']
    path.write_text('changed raw log')
    with pytest.raises(ValueError, match='日志'):
        reports.compile_report(project, p['id'], ReportRequest(kind='experiment', title='不可信报告', style='lab', sources=[run['id']]))
