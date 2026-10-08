"""本地科研工作台 HTTP 入口；默认仅供回环地址访问。"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, HTMLResponse
from pydantic import ValidationError
from .domain import Project, Note, Reading, RemoteConfig, ModelConfig, ExperimentSpec, ReportRequest
from .store import Store, safe_path, identifier, ROOT, now
from . import demo, literature, research, integrations, reports, experiments, batches
from .orchestrator import Scheduler


def create_app(store=None, background=True):
    store = store or Store()
    token = secrets.token_urlsafe(32)
    scheduler = Scheduler(store)

    @asynccontextmanager
    async def lifespan(app):
        if background:
            scheduler.acquire()
        task = asyncio.create_task(scheduler.run()) if background else None
        yield
        if task:
            scheduler.stop.set()
            await task

    app = FastAPI(title='研序 · 本地科研工作台', lifespan=lifespan)
    app.state.store = store

    @app.middleware('http')
    async def guard(request: Request, call_next):
        host = request.url.hostname
        if host not in ('127.0.0.1', 'localhost', 'testserver', '::1'):
            return JSONResponse({'detail': '仅允许本地工作台访问'}, status_code=403)
        if request.url.path.startswith('/api'):
            origin = request.headers.get('origin')
            if origin and origin not in ('http://127.0.0.1:8775', 'http://localhost:8775', 'http://127.0.0.1:5173', 'http://localhost:5173', 'http://testserver'):
                return JSONResponse({'detail': '请求来源不受信任'}, status_code=403)
            if request.url.path != '/api/session':
                supplied = request.headers.get('x-research-token') or request.cookies.get('research-session', '')
                if not secrets.compare_digest(supplied, token):
                    return JSONResponse({'detail': '本地会话失效，请刷新'}, status_code=403)
                if request.method not in ('GET', 'HEAD') and not secrets.compare_digest(request.headers.get('x-research-token', ''), token):
                    return JSONResponse({'detail': '写入操作缺少会话令牌'}, status_code=403)
            if int(request.headers.get('content-length', '0')) > 30 * 1024 * 1024:
                return JSONResponse({'detail': '请求不能超过 30 MiB'}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)

    @app.get('/api/session')
    def session():
        response = JSONResponse({'token': token, 'version': '0.1.0'})
        response.set_cookie('research-session', token, httponly=True, samesite='strict')
        return response

    @app.get('/api/projects')
    def projects():
        return store.list(kind='project')

    @app.post('/api/projects')
    def add_project(data: Project):
        id = identifier('project')
        return store.put('project', id, data.model_dump(), id=id)

    @app.post('/api/demo')
    def add_demo():
        return demo.create_demo(store)

    @app.put('/api/projects/{project}')
    def edit_project(project: str, data: Project):
        store.get(project)
        return store.put('project', project, data.model_dump(), id=project)

    @app.get('/api/projects/{project}/records')
    def records(project: str):
        return [r | {'stale': store.stale(r)} for r in store.list(project) if r['kind'] != 'project']

    @app.get('/api/records/{id}')
    def record(id: str, version: int | None = None):
        return store.get(id, version)

    @app.post('/api/projects/{project}/notes')
    def add_note(project: str, data: Note):
        store.get(project)
        store.check_refs(project, data.refs, dev_only=data.visibility == 'dev')
        return store.put('note', project, data.model_dump(), visibility=data.visibility)

    @app.put('/api/projects/{project}/notes/{id}')
    def update_note(project: str, id: str, data: Note):
        store.get(id, project=project)
        store.check_refs(project, data.refs, dev_only=data.visibility == 'dev')
        return store.put('note', project, data.model_dump(), id=id, visibility=data.visibility)

    def checked_reading(project, data):
        store.check_refs(project, data.refs, dev_only=True)
        paper = store.get(data.paper_id, project=project)
        if paper['content'].get('access') not in ('fulltext', 'teaching'):
            raise ValueError('只有摘要，不能保存全文级精读')
        permitted = {p['image'] for p in paper['content'].get('pages', [])}
        for old in store.list(project, 'reading'):
            permitted.update(f['asset'] for f in old['content']['figures'] if f['asset'])
        for figure in data.figures:
            if figure.asset and figure.asset not in permitted:
                raise ValueError('图像必须来自本项目论文或已导入图像')
        for formula in data.formulas:
            if formula.asset and formula.asset not in permitted:
                raise ValueError('公式截图不属于本项目原文')
            if formula.page is not None and formula.page not in {p['number'] for p in paper['content'].get('pages', [])}:
                raise ValueError('公式引用不存在的 PDF 页码')
            reports.math_svg(formula.latex)
            for term in formula.terms:
                reports.math_svg(term)
        return data.model_dump()

    @app.post('/api/projects/{project}/readings')
    def add_reading(project: str, data: Reading):
        return store.put('reading', project, checked_reading(project, data))

    @app.put('/api/projects/{project}/readings/{id}')
    def edit_reading(project: str, id: str, data: Reading, version: int):
        return store.put('reading', project, checked_reading(project, data), id=id, expected=version)

    @app.patch('/api/projects/{project}/papers/{id}')
    def paper_status(project: str, id: str, data: dict):
        record = store.get(id, project=project)
        if data.get('status') not in ('unread', 'reading', 'read', 'ignored'):
            raise ValueError('无效阅读状态')
        return store.put('paper', project, record['content'] | {'status': data['status'], 'feedback': str(data.get('feedback', ''))[:1000]}, id=id)

    @app.post('/api/projects/{project}/pdf')
    async def upload_pdf(project: str, file: UploadFile = File()):
        store.get(project)
        raw = await file.read(25 * 1024 * 1024 + 1)
        return await asyncio.to_thread(literature.import_pdf, store, project, Path(file.filename or 'paper.pdf').name, raw)

    @app.post('/api/projects/{project}/snapshot')
    async def snapshot(project: str, files: list[UploadFile] = File(), title: str = Form('代码快照')):
        store.get(project)
        if len(files) > 300:
            raise ValueError('最多选择 300 个代码文件')
        content = [(f.filename, await f.read(2 * 1024 * 1024 + 1)) for f in files]
        return literature.import_snapshot(store, project, content, title)

    @app.post('/api/projects/{project}/log')
    async def upload_log(project: str, file: UploadFile = File(), protocol: str = Form('未提供实验协议')):
        store.get(project)
        raw = await file.read(8 * 1024 * 1024 + 1)
        result = experiments.verify_log(raw.decode('utf-8'))
        blob = store.save_blob(raw, '.jsonl')
        return store.put('run', project, result | dict(title=Path(file.filename or '运行日志').name, blob=blob,
                         log_hash=hashlib.sha256(raw).hexdigest(), status='imported', protocol=protocol, refs=[]), visibility=result['visibility'])

    @app.post('/api/projects/{project}/search')
    def search(project: str, data: dict):
        if not store.get(project)['content'].get('search_consent'):
            raise ValueError('请先在项目设置中授权外发检索词')
        query = str(data.get('query', '')).strip()
        if not query or len(query) > 400:
            raise ValueError('请输入 1–400 字符的检索词')
        return store.enqueue(project, 'search', {'query': query})

    @app.post('/api/projects/{project}/doi')
    def doi(project: str, data: dict):
        return literature.crossref(store, project, str(data.get('doi', '')))

    @app.post('/api/projects/{project}/deep-read')
    def deep_read(project: str, data: dict):
        paper = store.get(data['paper_id'], project=project)
        if paper['content'].get('access') != 'fulltext':
            raise ValueError('请先导入 PDF 全文')
        if not store.get(project)['content'].get('model_consent'):
            raise ValueError('请先授权本项目材料发送给模型')
        return store.enqueue(project, 'read', {'paper_id': data['paper_id'], 'pages': data.get('pages', [1])})

    @app.post('/api/projects/{project}/recommend')
    def recommend(project: str):
        context = store.get(project)['content']
        if not context.get('search_consent') or not context.get('model_consent'):
            raise ValueError('按课题推荐需要同时授权文献检索与模型服务')
        return store.enqueue(project, 'recommend', {})

    @app.post('/api/projects/{project}/explain-code')
    def explain_code(project: str, data: dict):
        if not store.get(project)['content'].get('model_consent'):
            raise ValueError('代码讲解需要明确授权向模型发送选定文件')
        snapshot = store.get(data.get('snapshot_id', ''), project=project)
        if snapshot['kind'] != 'snapshot' or data.get('filename') not in snapshot['content']['files']:
            raise ValueError('代码不属于所选快照')
        return store.enqueue(project, 'explain-code', {key: data.get(key) for key in ('snapshot_id', 'filename', 'reading_id')})

    @app.post('/api/projects/{project}/propose')
    def propose(project: str):
        if not store.get(project)['content'].get('model_consent'):
            raise ValueError('请先配置模型及项目外发授权')
        return store.enqueue(project, 'propose', {})

    @app.get('/api/projects/{project}/planner-context')
    def planner_context(project: str):
        return research.planner_context(store, project)

    @app.get('/api/projects/{project}/local-search')
    def local_search(project: str, q: str):
        terms = ' '.join('"' + term.replace('"', '""') + '"' for term in q.split()[:10])
        if not terms:
            return []
        with store.connect() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM search WHERE search MATCH ? AND project=? LIMIT 30', (terms, project))]
        return [store.get(id) for id in ids]

    @app.post('/api/projects/{project}/reports')
    def report(project: str, data: ReportRequest):
        reports.compile_report(store, project, data)
        return store.enqueue(project, 'report', data.model_dump(mode='json'))

    @app.post('/api/math')
    def math(data: dict):
        return {'svg': reports.math_svg(str(data.get('latex', '')))}

    @app.get('/api/projects/{project}/jobs')
    def jobs(project: str):
        return store.jobs(project)

    @app.get('/api/projects/{project}/events')
    async def events(project: str, request: Request, after: int = 0):
        async def stream():
            last = request.headers.get('last-event-id', '')
            cursor = max(after, int(last)) if last.isdigit() else after
            while not await request.is_disconnected():
                rows = store.events(project, cursor)
                for row in rows:
                    cursor = row['seq']
                    yield 'id: ' + str(cursor) + '\ndata: ' + json.dumps(row, ensure_ascii=False) + '\n\n'
                if not rows:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(2)
        return StreamingResponse(stream(), media_type='text/event-stream')

    @app.get('/api/settings/model')
    def model_settings():
        return store.setting('model') or ModelConfig().model_dump()

    @app.put('/api/settings/model')
    def save_model(data: ModelConfig):
        parsed = urlsplit(data.base_url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('模型端点须为不含凭证参数的 HTTPS URL')
        return store.setting('model', data.model_dump())

    @app.post('/api/projects/{project}/remotes')
    def add_remote(project: str, data: RemoteConfig):
        store.get(project)
        return store.put('remote', project, data.model_dump())

    @app.post('/api/projects/{project}/remotes/{id}/doctor')
    def doctor(project: str, id: str, data: dict):
        config = store.get(id, project=project)['content']
        if not data.get('acknowledge'):
            raise ValueError('此操作会部署项目级 runner，需要明确确认')
        with integrations.ssh(config) as client:
            return integrations.deploy(client, config)

    @app.post('/api/projects/{project}/specs')
    def spec(project: str, data: ExperimentSpec):
        store.get(project)
        store.check_refs(project, data.refs, dev_only=data.phase == 'dev')
        store.get(data.snapshot_id, project=project)
        store.get(data.remote_id, project=project)
        return store.put('spec', project, data.model_dump(), visibility=data.phase)

    @app.post('/api/projects/{project}/batches')
    def batch_approval(project: str, data: dict):
        return batches.approve_batch(store, project, data.get('spec_ids', []), data.get('hashes', []),
                                     data.get('gpu_hours', 0), data.get('timeout_seconds', 0), data.get('acknowledge') is True)

    @app.post('/api/projects/{project}/batches/{id}/{action}')
    def batch_action(project: str, id: str, action: str):
        record = store.get(id, project=project)
        if record['kind'] != 'batch' or action not in ('submit', 'cancel'):
            raise ValueError('未知批次操作')
        return store.enqueue(project, 'batch-' + action, {'batch_id': id},
                             key='batch-submit:' + id if action == 'submit' else None)

    @app.post('/api/projects/{project}/specs/{id}/approve')
    def approve(project: str, id: str, data: dict):
        return experiments.approve(store, project, id, data.get('hash'), data.get('acknowledge') is True)

    @app.get('/api/projects/{project}/approvals')
    def approvals(project: str):
        with store.connect() as db:
            return [dict(row) for row in db.execute('SELECT id,spec_id,spec_hash,created FROM approvals WHERE project=?', (project,))]

    @app.post('/api/projects/{project}/approvals/{id}/{action}')
    def approval_action(project: str, id: str, action: str):
        with store.connect() as db:
            row = db.execute('SELECT payload FROM approvals WHERE id=? AND project=?', (id, project)).fetchone()
        if not row or action not in ('submit', 'sync', 'cancel'):
            raise ValueError('不允许的审批操作')
        if action == 'submit':
            approval = experiments.approved_payload(store, id)
            if approval['payload'].get('batch'):
                raise ValueError('批次成员须从批次入口按批准顺序统一启动')
        return store.enqueue(project, action, {'approval_id': id}, key='submit:' + id if action == 'submit' else None)

    @app.get('/api/projects/{project}/schedules')
    def schedules(project: str):
        with store.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM schedules WHERE project=?', (project,))]

    @app.post('/api/projects/{project}/schedules')
    def schedule(project: str, data: dict):
        if data.get('kind') not in ('search', 'weekly', 'propose', 'recommend'):
            raise ValueError('只支持论文检索、研究建议与周报调度')
        context = store.get(project)['content']
        if data['kind'] in ('search', 'recommend') and not context['search_consent']:
            raise ValueError('请先授权检索')
        if data['kind'] in ('propose', 'recommend') and not context['model_consent']:
            raise ValueError('请先授权模型')
        interval = int(data.get('interval_seconds', 604800))
        if interval < 3600 or interval > 31 * 86400:
            raise ValueError('调度间隔须为 1 小时至 31 天')
        payload = data.get('payload', {})
        if data['kind'] == 'weekly':
            if context['style'] == 'ask':
                raise ValueError('请先在汇报中心选择并保存排版风格')
            payload = {'kind': 'weekly', 'title': '每周研究进展', 'style': context['style'], 'mode': 'scroll'}
        if data['kind'] == 'search' and not str(payload.get('query', '')).strip():
            raise ValueError('定时检索需要明确检索词')
        id = identifier('schedule')
        with store.connect() as db:
            db.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?)', (id, project, data['kind'], interval,
                       (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat(), json.dumps(payload), 1))
        return {'id': id}

    @app.patch('/api/projects/{project}/schedules/{id}')
    def toggle_schedule(project: str, id: str, data: dict):
        with store.connect() as db:
            db.execute('UPDATE schedules SET enabled=? WHERE id=? AND project=?', (int(data.get('enabled') is True), id, project))
        return {'ok': True}

    @app.get('/api/files/{path:path}')
    def files(path: str):
        if not path.startswith(('blobs/', 'pages/', 'reports/')):
            raise HTTPException(404)
        file = safe_path(store.root, path, True)
        if path.startswith('reports/') and '/dist/' not in path:
            raise HTTPException(403)
        if file.suffix not in ('.png', '.jpg', '.jpeg', '.webp', '.pdf', '.html', '.zip', '.jsonl', '.txt', '.json'):
            raise HTTPException(403)
        response = FileResponse(file)
        if file.suffix == '.html':
            response.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
        return response

    @app.get('/{path:path}')
    def frontend(path: str):
        if path.startswith('api/'):
            raise HTTPException(404)
        dist = ROOT / 'dist'
        if path:
            candidate = safe_path(dist, path)
            if candidate.is_file():
                return FileResponse(candidate)
        if (dist / 'index.html').exists():
            return FileResponse(dist / 'index.html')
        return HTMLResponse('<p>前端尚未构建。请运行 npm run build，或使用 npm run dev。</p>')

    return app


app = create_app()
