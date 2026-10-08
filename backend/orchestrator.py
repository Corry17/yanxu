"""单进程持久调度器；恢复只重放幂等请求，不改变远端任务身份。"""
import asyncio
from datetime import datetime, timedelta, timezone
import fcntl
import json
import logging
from . import integrations, literature, research, reports, batches
from .domain import ReportRequest
from .store import now


class Scheduler:
    def __init__(self, store):
        self.store = store
        self.stop = asyncio.Event()
        self.lock = None

    def acquire(self):
        self.lock = (self.store.root / 'scheduler.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError('同一个数据目录只能启动一个调度进程')
        self.store.recover()

    def schedules(self):
        current = datetime.now(timezone.utc)
        with self.store.connect() as db:
            due = db.execute('SELECT * FROM schedules WHERE enabled=1 AND next_due<=?', (current.isoformat(),)).fetchall()
        for row in due:
            payload = json.loads(row['payload'])
            due_time = datetime.fromisoformat(row['next_due'])
            while due_time + timedelta(seconds=row['interval_seconds']) <= current:
                due_time += timedelta(seconds=row['interval_seconds'])
            if row['kind'] == 'weekly':
                end = due_time
                payload.update(start=(end - timedelta(days=7)).isoformat(), end=end.isoformat())
            self.store.enqueue(row['project'], row['kind'], payload, key='schedule:' + row['id'] + ':' + due_time.isoformat())
            next_due = datetime.fromisoformat(row['next_due'])
            while next_due <= current:
                next_due += timedelta(seconds=row['interval_seconds'])
            with self.store.connect() as db:
                db.execute('UPDATE schedules SET next_due=? WHERE id=?', (next_due.isoformat(), row['id']))

    def execute(self, job):
        project, payload, kind = job['project'], job['payload'], job['kind']
        if kind == 'search':
            return literature.search_arxiv(self.store, project, payload['query'])
        if kind == 'read':
            return research.deep_read(self.store, project, payload['paper_id'], payload['pages'])
        if kind == 'propose':
            return research.propose(self.store, project)
        if kind == 'recommend':
            return research.recommend(self.store, project)
        if kind == 'explain-code':
            return research.explain_code(self.store, project, payload['snapshot_id'], payload['filename'], payload.get('reading_id'))
        if kind in ('report', 'weekly'):
            return reports.export_report(self.store, project, ReportRequest.model_validate(payload))
        if kind == 'batch-submit':
            return batches.submit_batch(self.store, project, payload['batch_id'])
        if kind == 'batch-cancel':
            return batches.cancel_batch(self.store, project, payload['batch_id'])
        if kind == 'submit':
            return integrations.submit(self.store, payload['approval_id'])
        if kind == 'sync':
            return integrations.sync(self.store, payload['approval_id'])
        if kind == 'cancel':
            return integrations.sync(self.store, payload['approval_id'], cancel=True)
        raise ValueError('未知任务类型')

    async def run(self):
        if self.lock is None:
            self.acquire()
        last_poll = 0
        try:
            while not self.stop.is_set():
                try:
                    await asyncio.to_thread(self.schedules)
                    job = await asyncio.to_thread(self.store.claim)
                    if job:
                        try:
                            result = await asyncio.to_thread(self.execute, job)
                            self.store.finish(job['id'], result)
                            self.store.event(job['project'], 'job.done', {'id': job['id'], 'kind': job['kind']})
                        except Exception as exc:
                            self.store.finish(job['id'], error=str(exc))
                            self.store.event(job['project'], 'job.failed', {'id': job['id'], 'message': str(exc)})
                    tick = asyncio.get_running_loop().time()
                    if tick - last_poll > 20:
                        last_poll = tick
                        await asyncio.to_thread(self.poll_remote)
                except Exception:
                    logging.exception('调度检查失败，保留队列等待下一次检查')
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass
        finally:
            self.lock.close()

    def poll_remote(self):
        with self.store.connect() as db:
            jobs = db.execute("SELECT * FROM jobs WHERE kind IN ('submit','batch-submit') AND status='done'").fetchall()
        tasks = []
        for job in jobs:
            payload = json.loads(job['payload'])
            approvals = [payload['approval_id']] if job['kind'] == 'submit' else self.store.get(payload['batch_id'])['content']['approvals']
            tasks.extend((job, approval) for approval in approvals)
        for job, approval in tasks:
            run_id = 'run-' + approval.removeprefix('approval-')
            try:
                run = self.store.get(run_id)
                if run['content']['status'] in ('done', 'failed', 'blocked', 'cancelled', 'interrupted'):
                    continue
            except ValueError:
                pass
            try:
                integrations.sync(self.store, approval)
            except Exception as exc:
                # 连接失败不改实验结论，也不重新提交训练。
                self.store.event(job['project'], 'remote.disconnected', {'approval': approval, 'message': str(exc)})
