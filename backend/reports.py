"""科研数据先冻结，再映射到已有 HTML Skill 的严格项目契约。"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from functools import lru_cache
import hashlib
import json
import shutil
import subprocess
import sys
from PIL import Image
from .domain import ReportRequest, digest
from .experiments import parse_log, compare_runs
from .store import ROOT, safe_path, now, identifier

SKILL = ROOT / 'vendor/summary-to-html'


def check_skill():
    source = json.loads((SKILL / 'provenance.json').read_text())
    for relative, expected in source['files'].items():
        if hashlib.sha256((SKILL / relative).read_bytes()).hexdigest() != expected:
            raise ValueError('HTML Skill 快照已变化，请做升级审核与回归测试')


def tool(action, project):
    check_skill()
    proc = subprocess.run([sys.executable, str(SKILL / 'scripts/project_tool.py'), action, str(project)],
                          capture_output=True, text=True, timeout=90)
    if proc.returncode:
        raise ValueError('HTML 素材校验失败：' + proc.stderr[-1200:])
    return json.loads(proc.stdout)


def render(payload):
    node = shutil.which('node')
    if not node:
        raise ValueError('需要 Node.js 来生成离线公式 SVG')
    result = subprocess.run([node, str(ROOT / 'packages/research-renderer/render.mjs')],
                            input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('公式或报告渲染失败，请核对内容：' + result.stderr[-700:])
    return result.stdout


@lru_cache(maxsize=200)
def math_svg(latex):
    return render({'operation': 'math', 'latex': latex})


def compile_report(store, project, request: ReportRequest):
    context = store.get(project)
    zone = ZoneInfo(context['content'].get('timezone', 'Asia/Shanghai'))
    if request.start_day and request.end_day:
        request = request.model_copy(update={
            'start': datetime.combine(request.start_day, time.min, tzinfo=zone),
            'end': datetime.combine(request.end_day + timedelta(days=1), time.min, tzinfo=zone)})
    records = [store.get(id, project=project) for id in dict.fromkeys(request.sources)]
    if request.kind == 'weekly':
        cutoff = min(request.end, datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        historical = store.asof(project, cutoff)
        context = next((r for r in historical if r['id'] == project), context)
        records = [r for r in historical if r['kind'] in ('note', 'reading', 'run', 'code-study')
                   and request.start <= datetime.fromisoformat(r['created']) < request.end]
    if any(r['visibility'] == 'final' for r in records) and not request.include_final:
        if request.kind == 'weekly':
            records = [r for r in records if r['visibility'] == 'dev']
        else:
            raise ValueError('最终测试内容需显式选择最终报告范围')
    if request.kind == 'paper' and not records:
        raise ValueError('请选择精读记录')
    if request.kind == 'experiment' and not records:
        raise ValueError('请选择实验记录')
    if request.kind == 'paper' and any(r['kind'] != 'reading' for r in records):
        raise ValueError('论文报告只能使用精读记录')
    if request.kind == 'experiment' and any(r['kind'] != 'run' for r in records):
        raise ValueError('实验报告只能使用已导入或核验的运行记录')
    sections = []
    if request.kind == 'experiment' and len(records) > 1:
        sections.append(dict(type='comparison', label='相同协议内的实验对照',
                             content=compare_runs(store, project, [r['id'] for r in records], request.include_final)))
    if request.kind == 'weekly':
        sections.append(dict(type='text', label='目标与本周研究问题', content={
            'text': context['content']['question'], 'items': [context['content'].get('goals', '尚未记录目标')]}))
        notes = [r for r in records if r['kind'] == 'note']
        for label, categories in [('新增认识与进展', ('progress', 'decision', 'lesson')),
                                  ('问题、阻塞与下周验证', ('question', 'blocker', 'hypothesis'))]:
            items = [r['content']['title'] + '：' + r['content']['text'] + ('（已核对记录）' if r['content'].get('reviewed') else '（用户记录/待验证）')
                     for r in notes if r['content']['category'] in categories]
            sections.append(dict(type='text', label=label, content={'text': '' if items else '本时间范围内尚无对应记录。', 'items': items}))
    for record in records:
        if digest(record['content']) != record['hash']:
            raise ValueError('证据内容与保存的指纹不一致，拒绝生成报告')
        if record['kind'] == 'run' and record['content'].get('blob'):
            raw = safe_path(store.root, record['content']['blob'], True).read_bytes()
            if hashlib.sha256(raw).hexdigest() != record['content'].get('log_hash'):
                raise ValueError('原日志内容已改变')
            parsed = parse_log(raw.decode('utf-8'))
            if parsed['metrics'] != record['content'].get('metrics', []):
                raise ValueError('报告指标与原日志不一致')
        if record['kind'] == 'code-study':
            sections.append(dict(type='code-study', label=record['content']['title'], content=deepcopy(record['content'])))
        if record['kind'] in ('reading', 'run'):
            content = deepcopy(record['content'])
            if record['kind'] == 'run' and content.get('spec_id'):
                spec = store.get(content['spec_id'], project=project)['content']
                content.update(hypothesis=spec['hypothesis'], protocol=spec['protocol'])
            if request.kind == 'weekly':
                summary = content.get('summary') if record['kind'] == 'reading' else content.get('verdict', 'INCONCLUSIVE') + '：' + '；'.join(content.get('problems', []))
                sections.append(dict(type='text', label=content['title'] + ' · 本周认识',
                                     content={'text': summary or '暂无可核验结论。', 'items': content.get('next_steps', [])}))
            sections.append(dict(type='reading' if record['kind'] == 'reading' else 'run',
                                 label=('证据附录 · ' if request.kind == 'weekly' else '') + content['title'], content=content))
    if not sections:
        sections.append(dict(type='text', label='证据缺口', content={'text': '尚无本期材料，不生成虚构进展。', 'items': []}))
    refs = []
    for record in [context] + records:
        refs.append(dict(id=record['id'], version=record['version'], hash=record['hash'], title=record['content'].get('title', record['kind'])))
        if record['kind'] == 'reading':
            for ref in record['content'].get('refs', []):
                evidence = store.get(ref['id'], ref['version'], project)
                refs.append(dict(id=evidence['id'], version=evidence['version'], hash=evidence['hash'], title=evidence['content'].get('title', '来源')))
    stale = [r['content']['title'] for r in records if store.stale(r)]
    if stale:
        sections.insert(0, dict(type='text', label='来源更新提醒', content={'text': '以下解释引用旧版本，需要重新核对。', 'items': stale}))
    data = dict(title=request.title, kind=request.kind, style=request.style, mode=request.mode,
                subtitle={'paper': '公式、图像与实现，共同构成理解的证据。', 'experiment': '先核对实验协议，再解释结果与下一步。',
                          'weekly': '记录新增的认识，而不只是完成的动作。'}[request.kind],
                created=now(), demo=context['content'].get('demo', False), sections=sections,
                evidence=refs, period=f'{request.start.astimezone(zone).isoformat()} — {request.end.astimezone(zone).isoformat()}' if request.start else '',
                resources=True)
    return data, records


def export_report(store, project, request):
    data, records = compile_report(store, project, request)
    id = identifier('report')
    work = safe_path(store.root, 'reports/' + id)
    work.parent.mkdir(exist_ok=True)
    tool('init', work)
    config = json.loads((work / 'project.json').read_text())
    config.update(title=request.title, purpose='科研' + request.kind, mode=request.mode, style='custom',
                  style_notes=request.style, outline=[], resources=[])
    resources = []
    remap = []

    def add_image(original, title, caption):
        asset_id = f'figure-{len(resources) + 1}'
        relative = f'materials/images/{asset_id}{original.suffix.lower()}'
        target = work / relative
        target.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(original, target)
        resources.append(dict(id=asset_id, path=relative, title=title, use='embed', alt=title, caption=caption))
        return asset_id

    for section in data['sections']:
        if section['type'] != 'reading':
            continue
        for formula in section['content'].get('formulas', []):
            if formula.get('asset'):
                original = safe_path(store.root, formula['asset'], True)
                formula['asset'] = add_image(original, formula['title'] + ' · 原文页', formula['source'])
                remap.append((formula, 'asset'))
        for figure in section['content'].get('figures', []):
            if not figure.get('asset'):
                continue
            original = safe_path(store.root, figure['asset'], True)
            if original.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
                raise ValueError('科研图必须为已验证静态位图')
            figure['asset'] = add_image(original, figure['title'], figure['source'])
            remap.append((figure, 'asset'))
            with Image.open(original) as image:
                for region in figure.get('regions', []):
                    if not region.get('box'):
                        continue
                    x, y, w, h = region['box']
                    crop = image.crop((int(x * image.width), int(y * image.height),
                                       max(int((x + w) * image.width), int(x * image.width) + 1),
                                       max(int((y + h) * image.height), int(y * image.height) + 1)))
                    crop_path = work / f'crop-{len(resources)}.png'
                    crop.save(crop_path)
                    region['crop'] = add_image(crop_path, region['label'], '原图局部裁剪，需结合整图阅读')
                    remap.append((region, 'crop'))
    config['resources'] = resources
    config['outline'] = [dict(id=f'section-{i}', title=section['label']) for i, section in enumerate(data['sections'])]
    (work / 'project.json').write_text(json.dumps(config, ensure_ascii=False, indent=2))
    (work / 'research-report.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tool('scan', work)
    tool('prepare', work)
    output = work / 'dist/v001'
    manifest = json.loads((output / 'manifest.json').read_text())
    mapping = {r['id']: r['href'] for r in manifest['resources']}
    for item, field in remap:
        item[field] = mapping[item[field]]
    html = render(data)
    (output / 'index.html').write_text(html, encoding='utf-8')
    result = tool('pack', work)
    return store.put('report', project, dict(title=request.title, report_type=request.kind,
                     style=request.style, mode=request.mode, created=data['created'],
                     entry=str((output / 'index.html').relative_to(store.root)),
                     archive=str(Path(result['archive']).relative_to(store.root)),
                     refs=[{'id': r['id'], 'version': r['version']} for r in records],
                     snapshot=data, warnings=['通过静态校验；导出后仍建议检查实际图片与打印排版。']),
                     id=id, visibility='final' if any(r['visibility'] == 'final' for r in records) else 'dev')
