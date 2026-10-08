"""本地项目与科研报告命令入口，不绕过科研或打包校验。"""
import argparse
from datetime import datetime
import json
from .store import Store
from .domain import ReportRequest
from .reports import export_report


def main():
    parser = argparse.ArgumentParser(description='研序科研工作台')
    sub = parser.add_subparsers(dest='action', required=True)
    listing = sub.add_parser('list')
    listing.add_argument('--project')
    report = sub.add_parser('report')
    report.add_argument('project')
    report.add_argument('--kind', choices=['paper', 'experiment', 'weekly'], required=True)
    report.add_argument('--source', action='append', default=[])
    report.add_argument('--title', default='科研汇报')
    report.add_argument('--style', choices=['academic', 'paper', 'lab'], required=True)
    report.add_argument('--mode', choices=['scroll', 'deck'], default='scroll')
    report.add_argument('--start', type=datetime.fromisoformat)
    report.add_argument('--end', type=datetime.fromisoformat)
    report.add_argument('--include-final', action='store_true')
    args = parser.parse_args()
    store = Store()
    if args.action == 'list':
        result = [{'id': r['id'], 'version': r['version'], 'kind': r['kind'], 'title': r['content'].get('title')}
                  for r in store.list(project=args.project, kind=None if args.project else 'project')]
    else:
        result = export_report(store, args.project, ReportRequest(kind=args.kind, title=args.title, sources=args.source,
                               style=args.style, mode=args.mode, start=args.start, end=args.end, include_final=args.include_final))
        result = {'entry': str(store.root / result['content']['entry']), 'archive': str(store.root / result['content']['archive'])}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
