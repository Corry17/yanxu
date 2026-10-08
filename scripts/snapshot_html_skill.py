"""为批准的 HTML 依赖建立只读内容快照，不修改外部 Skill。"""
from pathlib import Path
import argparse
import hashlib
import json

FILES = ('SKILL.md', 'scripts/project_tool.py', 'scripts/validate_html.py',
         'references/project-contract.md', 'references/content-and-media.md',
         'references/style-presets.md', 'assets/project-template.json', 'assets/style-preview.html')
ROOT = Path(__file__).resolve().parents[1]


def snapshot(source):
    destination = ROOT / 'vendor/summary-to-html'
    if destination.exists():
        raise ValueError('依赖快照已存在；升级需要显式审核新版本')
    entries = {}
    content = {}
    for relative in FILES:
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError('依赖文件缺失或使用符号链接')
        raw = path.read_bytes()
        content[relative] = raw
        entries[relative] = hashlib.sha256(raw).hexdigest()
    for relative, raw in content.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (destination / 'provenance.json').write_text(json.dumps({
        'name': 'summary-to-html', 'source': str(source), 'files': entries
    }, ensure_ascii=False, indent=2))
    print('HTML Skill 内容快照已创建，共', len(entries), '个文件')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    snapshot(parser.parse_args().source)
