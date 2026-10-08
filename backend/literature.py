"""论文导入、固定服务检索与证据级去重。"""
from __future__ import annotations
from pathlib import Path
from urllib.parse import quote
import json
import hashlib
import re
import subprocess
import sys
import httpx
from defusedxml import ElementTree
from .store import ROOT, safe_path


def public_get(url, params=None):
    # 仅允许固定公共服务，禁止重定向到任意来源。
    if not url.startswith(('https://export.arxiv.org/api/query', 'https://api.crossref.org/works/')):
        raise ValueError('不允许的文献服务')
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        with client.stream('GET', url, params=params, headers={'User-Agent': 'ResearchWorkbench/0.1 (local academic reader)'}) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 4 * 1024 * 1024:
                    raise ValueError('文献响应超出大小限制')
    return bytes(content)


def search_arxiv(store, project, query):
    context = store.get(project)['content']
    if not context.get('search_consent'):
        raise ValueError('请先授权发送检索词给文献服务')
    if not query or len(query) > 400:
        raise ValueError('检索词须为 1–400 字符')
    text = public_get('https://export.arxiv.org/api/query', {'search_query': 'all:' + query,
                      'start': 0, 'max_results': 15, 'sortBy': 'relevance'})
    root = ElementTree.fromstring(text)
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    existing = {r['content'].get('canonical'): r for r in store.list(project, 'paper')}
    results = []
    for entry in root.findall('a:entry', ns):
        url = entry.findtext('a:id', '', ns).replace('http:', 'https:')
        if not re.fullmatch(r'https://arxiv.org/abs/[A-Za-z0-9./-]+', url):
            continue
        canonical = re.sub(r'v\d+$', '', url)
        title = ' '.join(entry.findtext('a:title', '', ns).split())
        if canonical in existing:
            results.append(existing[canonical])
            continue
        abstract = ' '.join(entry.findtext('a:summary', '', ns).split())
        content = dict(title=title, canonical=canonical, url=url, abstract=abstract,
                       authors=[e.findtext('a:name', '', ns) for e in entry.findall('a:author', ns)],
                       published=entry.findtext('a:published', '', ns), access='abstract',
                       status='unread', query=query, reason=f'由检索词「{query}」召回；请核对与当前瓶颈的适配性。',
                       caution='摘要级推荐：尚未取得全文，不能确认具体公式、图号或复现效果。')
        results.append(store.put('paper', project, content))
    store.event(project, 'literature.search', {'query': query, 'count': len(results)})
    return results


def crossref(store, project, doi):
    if not store.get(project)['content'].get('search_consent'):
        raise ValueError('尚未授权文献检索')
    if not re.fullmatch(r'10\.\d{4,9}/\S{1,180}', doi):
        raise ValueError('无效 DOI')
    data = json.loads(public_get('https://api.crossref.org/works/' + quote(doi, safe='')))['message']
    canonical = 'https://doi.org/' + doi.lower()
    prior = next((r for r in store.list(project, 'paper') if r['content'].get('canonical') == canonical), None)
    if prior:
        return prior
    return store.put('paper', project, dict(title=(data.get('title') or [doi])[0], canonical=canonical,
                     url=canonical, access='metadata', status='unread', abstract='',
                     authors=[' '.join([a.get('given', ''), a.get('family', '')]) for a in data.get('author', [])],
                     reason='DOI 元数据已核对；全文与内容结论仍待导入。'))


def import_pdf(store, project, filename, raw):
    if not raw.startswith(b'%PDF-') or len(raw) > 25 * 1024 * 1024:
        raise ValueError('请上传不超过 25 MiB 的 PDF')
    blob = store.save_blob(raw, '.pdf')
    id_hash = hashlib.sha256(raw).hexdigest()
    prior = next((r for r in store.list(project, 'paper') if r['content'].get('pdf_hash') == id_hash), None)
    if prior:
        return prior
    output = safe_path(store.root, 'pages/' + id_hash)
    output.mkdir(parents=True, exist_ok=True)
    # 固定的解析工作器；不执行论文附件或来源中的命令。
    proc = subprocess.run([sys.executable, str(ROOT / 'backend/pdf_worker.py'),
                           str(safe_path(store.root, blob, True)), str(output)],
                          capture_output=True, text=True, timeout=90, check=False)
    if proc.returncode:
        raise ValueError('PDF 解析失败或资源超限；原件已保留。' + proc.stderr[-250:])
    parsed = json.loads(proc.stdout)
    pages = [{'number': page['number'], 'text': page['text'],
              'image': str((output / page['image']).relative_to(store.root))} for page in parsed['pages']]
    return store.put('paper', project, dict(title=filename, blob=blob, pdf_hash=id_hash,
                     canonical='sha256:' + id_hash, access='fulltext', pages=pages,
                     abstract=pages[0]['text'][:1500] if pages else '', status='unread',
                     reason='本地原文；页码与图像已绑定内容 hash。',
                     caution='页图已生成；图像内容尚须人工或授权视觉模型核对。'))


def import_snapshot(store, project, files, title):
    if not files or len(files) > 300:
        raise ValueError('快照需要 1–300 个显式选定文件')
    result = {}
    total = 0
    for name, content in files:
        safe_path(store.root, name)
        if name in result:
            raise ValueError('快照存在重复路径')
        suffix = Path(name).suffix.lower()
        if suffix not in ('.py', '.json', '.toml', '.txt', '.yaml', '.yml', '.cfg'):
            raise ValueError('不支持的快照类型：' + suffix)
        if any(word in name.lower() for word in ('.env', 'credential', 'id_rsa', 'id_ed25519', 'secret')):
            raise ValueError('快照不可包含凭证文件')
        total += len(content)
        if len(content) > 2 * 1024 * 1024 or total > 20 * 1024 * 1024:
            raise ValueError('代码快照超过大小限制')
        text = content.decode('utf-8')
        result[name] = dict(blob=store.save_blob(content, suffix), sha256=hashlib.sha256(content).hexdigest(),
                            size=len(content), text=text)
    return store.put('snapshot', project, dict(title=title, files=result,
                     status='static', note='仅保存与展示；未执行任何上传代码。'))
