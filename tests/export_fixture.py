"""为浏览器测试准备可迁移的离线报告，不修改真实研究数据。"""
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.store import Store
from backend.demo import create_demo
from backend.domain import ReportRequest
from backend.reports import export_report


def build(output):
    output = Path(output).resolve()
    workspace = Path(__file__).resolve().parents[1]
    if not output.is_relative_to(workspace / '.research/browser-results'):
        raise ValueError('测试产物只写入授权测试目录')
    store = Store(output / 'local')
    project = create_demo(store)
    reading = store.list(project['id'], 'reading')[0]
    request = ReportRequest(kind='paper', title='离线教学精读', sources=[reading['id']], style='paper', mode='deck')
    report = export_report(store, project['id'], request)
    original = store.root / report['content']['entry']
    moved = output / 'portable'
    shutil.copytree(original.parent, moved)
    return str(moved / 'index.html')


if __name__ == '__main__':
    print(json.dumps({'entry': build(sys.argv[1])}))
