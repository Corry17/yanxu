#!/usr/bin/env python3
"""初始化、扫描、准备及打包离线内容项目。不会执行素材、联网或改写原件。"""

import argparse
import hashlib
import html
import json
import math
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from validate_html import validate

SKILL = Path(__file__).resolve().parents[1]
MAX_ITEMS, MAX_DEPTH = 2000, 12
MAX_FILE, MAX_TOTAL = 1024 ** 3, 4 * 1024 ** 3
ID_PATTERN = r'[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?'
KINDS = {
    'images': {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif'},
    'videos': {'.mp4', '.webm'},
    'audio': {'.mp3', '.wav', '.ogg', '.m4a'},
    'captions': {'.vtt'},
    'files': {'.pdf', '.txt', '.md', '.csv', '.json', '.docx', '.pptx', '.xlsx',
              '.zip', '.mov', '.avi', '.heic', '.tif', '.tiff', '.srt'},
}
SENSITIVE = {'.env', '.pem', '.key', '.p12', '.pfx', '.keystore'}
SECRET_NAMES = {'id_rsa', 'id_ed25519', 'credentials.json'}
TOP_FIELDS = {'schema_version', 'slug', 'title', 'purpose', 'audience', 'content_policy',
              'mode', 'style', 'style_notes', 'duration_minutes', 'outline', 'resources', 'links', 'notes'}
RESOURCE_FIELDS = {'id', 'path', 'title', 'use', 'alt', 'caption', 'section',
                   'poster_id', 'captions_id', 'transcript'}


def fail(message):
    raise ValueError(message)


def identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value):
        fail('{} 必须是 1–48 位小写字母、数字或连字符，首尾为字母/数字。'.format(label))
    return value


def text(value, label, required=False):
    if not isinstance(value, str) or (required and not value.strip()):
        fail('{} 必须是{}文本。'.format(label, '非空' if required else ''))
    if '\x00' in value:
        fail('{} 不能含空字符。'.format(label))
    return value


def blocked(name):
    return name.startswith('.') or Path(name).suffix.lower() in SENSITIVE or name.lower() in SECRET_NAMES


def project_root(value):
    path = Path(value).absolute()
    if path.is_symlink():
        fail('项目根目录不能是符号链接。')
    return path.resolve()


def local_path(root, relative, must_exist=True):
    if not isinstance(relative, str) or any(ord(c) < 32 or ord(c) == 127 for c in relative):
        fail('本地路径必须是无控制字符的文本。')
    parts = relative.split('/')
    if '\\' in relative or ':' in relative or any(p in ('', '.', '..') for p in parts):
        fail('路径只能使用包内相对位置，不能含绝对路径、..、反斜杠：{}'.format(relative))
    path = root
    for part in parts:
        if blocked(part):
            fail('不能选择隐藏或敏感文件：{}'.format(relative))
        path = path / part
        if path.is_symlink():
            fail('不能跟随符号链接：{}'.format(relative))
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        fail('路径越出项目：{}'.format(relative))
    if must_exist and not path.is_file():
        fail('文件不存在或不是普通文件：{}'.format(relative))
    return path


def load_json(path):
    if path.stat().st_size > 1024 ** 2:
        fail('JSON 配置超过 1 MiB。')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('JSON 字段重复：{}'.format(key))
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda value: fail('非法 JSON 数值：{}'.format(value)))


def write_json(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def kind_of(path):
    return next((kind for kind, suffixes in KINDS.items() if path.suffix.lower() in suffixes), 'reference')


def external_url(value):
    text(value, 'url', True)
    if any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value:
        fail('外链包含空白或反斜杠。')
    try:
        parsed = urlsplit(value)
        parsed.port
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
            fail('外链必须是无用户名/密码的完整 HTTP(S) URL。')
    except ValueError as exc:
        fail('外链格式错误：{}'.format(exc))
    return value


def load_project(root):
    config = load_json(local_path(root, 'project.json'))
    if not isinstance(config, dict) or set(config) - TOP_FIELDS:
        fail('project.json 必须是对象，且不包含未知顶层字段。')
    if type(config.get('schema_version')) is not int or config['schema_version'] != 1:
        fail('仅支持 schema_version=1。')
    identifier(config.get('slug'), 'slug')
    text(config.get('title'), 'title', True)
    for field in ('purpose', 'audience', 'content_policy', 'style_notes', 'notes'):
        text(config.get(field, ''), field)
    if config.get('mode') not in ('scroll', 'deck', 'custom'):
        fail('mode 必须是 scroll/deck/custom。')
    if config.get('style') not in ('ask', 'brief', 'editorial', 'terminal', 'dashboard', 'notebook', 'spotlight', 'minimal', 'academic', 'swiss', 'gallery', 'blueprint', 'pastel', 'custom'):
        fail('style 必须是已知风格、ask 或 custom。')
    duration = config.get('duration_minutes')
    if duration is not None and (type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0):
        fail('duration_minutes 必须是正数或 null。')
    for field in ('outline', 'resources', 'links'):
        if not isinstance(config.get(field), list) or len(config[field]) > MAX_ITEMS:
            fail('{} 必须是最多 {} 项的数组。'.format(field, MAX_ITEMS))
    return config


def init_project(root, title):
    identifier(root.name, '项目目录名')
    text(title, 'title', True)
    if root.exists():
        fail('项目目录已存在，未做任何覆盖。')
    config = load_json(SKILL / 'assets/project-template.json')
    config.update(slug=root.name, title=title)
    root.mkdir(parents=True, exist_ok=False)
    for folder in ('docs', 'images', 'videos', 'audio', 'files'):
        (root / 'materials' / folder).mkdir(parents=True)
    (root / 'preview').mkdir()
    (root / 'dist').mkdir()
    write_json(root / 'project.json', config)
    with (root / 'BRIEF.txt').open('x', encoding='utf-8') as stream:
        stream.write('用途：可以是答辩、汇报、作品集、教程、资料导航或任意自定义内容。\n'
                     '受众与时长：\n内容要求：保留原文 / 可改写 / 原创构思。\n'
                     '章节与顺序：\n样式要求：先看预览，也可以直接指定。\n'
                     '图片、视频的位置和说明：\n需要能点开或下载的文件：\n'
                     '外部链接：\n保密或不能对外分享的材料：\n'
                     '\n将原件放入 materials 对应目录；不必自己写 JSON，可让助手代填。\n')
    return {'project': str(root), 'message': '项目骨架已创建，请放入素材并填写需求。'}


def scan_project(root):
    load_project(root)
    materials = local_path(root, 'materials', must_exist=False)
    if not materials.is_dir():
        fail('materials 目录不存在。')
    entries, skipped = [], []
    count = 0
    def walk_error(error):
        raise error
    for current, dirs, files in os.walk(materials, followlinks=False, onerror=walk_error):
        current = Path(current)
        if len(current.relative_to(materials).parts) > MAX_DEPTH:
            fail('素材目录超过最大深度 {}。'.format(MAX_DEPTH))
        count += len(dirs) + len(files)
        if count > MAX_ITEMS:
            fail('扫描超过 {} 项，未截断结果；请缩小目录。'.format(MAX_ITEMS))
        kept = []
        for name in sorted(dirs):
            child = current / name
            if child.is_symlink() or blocked(name):
                skipped.append({'path': child.relative_to(root).as_posix(), 'reason': '隐藏/敏感目录或符号链接'})
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            child = current / name
            relative = child.relative_to(root).as_posix()
            if child.is_symlink() or blocked(name) or not child.is_file():
                skipped.append({'path': relative, 'reason': '隐藏/敏感文件、符号链接或非普通文件'})
                continue
            size = child.stat().st_size
            entries.append({'path': relative, 'id': 'asset-' + hashlib.sha256(relative.encode()).hexdigest()[:12],
                            'kind': kind_of(child), 'size': size, 'use': 'reference',
                            'warning': '超过单文件限制' if size > MAX_FILE else ''})
    return {'files': entries, 'skipped': skipped, 'note': '仅目录清单；不等于已解析内容，也不会自动发布。'}


def named_items(items, label, fields):
    result = {}
    for item in items:
        if not isinstance(item, dict) or set(item) - fields:
            fail('{} 包含非法对象或未知字段。'.format(label))
        key = identifier(item.get('id'), label + '.id')
        if key in result:
            fail('{} ID 重复：{}'.format(label, key))
        text(item.get('title'), label + '.title', True)
        result[key] = item
    return result


def plan_resources(root, config):
    sections = named_items(config['outline'], 'outline', {'id', 'title', 'layout', 'notes', 'asset_ids'})
    resources = named_items(config['resources'], 'resources', RESOURCE_FIELDS)
    links = named_items(config['links'], 'links', {'id', 'title', 'url', 'section'})
    planned, total = [], 0
    for item in list(resources.values()) + list(links.values()):
        if 'section' in item:
            identifier(item['section'], 'section')
            if item['section'] not in sections:
                fail('未知章节：{}'.format(item['section']))
    for section in sections.values():
        for field in ('layout', 'notes'):
            text(section.get(field, ''), field)
        ids = section.get('asset_ids', [])
        if not isinstance(ids, list) or any(not isinstance(key, str) or key not in resources for key in ids):
            fail('章节 asset_ids 引用了不存在的素材。')
    for item in links.values():
        external_url(item.get('url'))
    for item in resources.values():
        relative = text(item.get('path'), 'resource.path', True)
        if not relative.startswith('materials/'):
            fail('资源必须位于 materials/：{}'.format(relative))
        path = local_path(root, relative)
        kind = kind_of(path)
        use = item.get('use', 'reference')
        if use not in ('reference', 'embed', 'attachment'):
            fail('use 必须是 reference/embed/attachment。')
        for field in ('alt', 'caption', 'transcript', 'poster_id', 'captions_id'):
            if field in item:
                text(item[field], field)
        if use != 'reference' and kind == 'reference':
            fail('该类型只能分析，不能直接交付：{}'.format(relative))
        if use == 'embed' and kind not in ('images', 'videos', 'audio', 'captions'):
            fail('该格式不能直接嵌入，请作为附件或先转换：{}'.format(relative))
        if use == 'embed' and kind == 'images':
            text(item.get('alt'), '图片 alt', True)
        if any(field in item for field in ('poster_id', 'captions_id', 'transcript')) and kind != 'videos':
            fail('poster_id/captions_id/transcript 仅适用于视频。')
        size = path.stat().st_size
        if use != 'reference':
            if size > MAX_FILE:
                fail('选定文件超过 1 GiB：{}'.format(relative))
            total += size
            planned.append({'item': item, 'path': path, 'kind': kind, 'size': size, 'use': use})
    if total > MAX_TOTAL:
        fail('选定素材总大小超过 4 GiB。')
    delivered = {entry['item']['id']: entry for entry in planned}
    for entry in planned:
        for field, kind in (('poster_id', 'images'), ('captions_id', 'captions')):
            if field in entry['item']:
                related = delivered.get(entry['item'][field])
                if related is None or related['kind'] != kind:
                    fail('{} 必须引用已交付的 {} 素材。'.format(field, kind))
    return planned


def fingerprint(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def file_hash(path):
    before = fingerprint(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if before != fingerprint(path):
        fail('读取期间文件发生变化：{}'.format(path.name))
    return digest.hexdigest()


def copy_checked(source, target, expected):
    digest = hashlib.sha256()
    with source.open('rb') as src, target.open('xb') as dst:
        for block in iter(lambda: src.read(1024 * 1024), b''):
            digest.update(block)
            dst.write(block)
    if digest.hexdigest() != expected:
        fail('复制期间素材发生变化，发布目录不完整：{}'.format(source.name))


def resource_page(manifest):
    esc = html.escape
    cards = []
    for entry in manifest['resources']:
        title, href = esc(entry['title']), esc(entry['href'], quote=True)
        open_href = esc(entry.get('preview_href', entry['href']), quote=True)
        open_label = '打开文本预览' if entry.get('preview_href') else '打开文件'
        media = ''
        if entry['use'] == 'embed' and entry['kind'] == 'images':
            media = '<a href="{}" target="_blank" rel="noopener noreferrer"><img src="{}" alt="{}" loading="lazy"></a>'.format(href, href, esc(entry['alt'], quote=True))
        elif entry['use'] == 'embed' and entry['kind'] in ('videos', 'audio'):
            tag = 'video' if entry['kind'] == 'videos' else 'audio'
            poster = ' poster="{}"'.format(esc(entry['poster_href'], quote=True)) if entry.get('poster_href') else ''
            track = '<track kind="captions" src="{}" srclang="zh" label="字幕">'.format(esc(entry['captions_href'], quote=True)) if entry.get('captions_href') else ''
            media = '<{0} controls playsinline preload="metadata"{1}><source src="{2}" type="{3}">{4}浏览器不支持播放，请下载文件。</{0}><p>若无法播放，请下载后用本地播放器打开。</p>'.format(tag, poster, href, entry['mime'], track)
        caption = '<p>{}</p>'.format(esc(entry['caption'])) if entry.get('caption') else ''
        transcript = '<details><summary>视频文字说明</summary><p>{}</p></details>'.format(esc(entry['transcript'])) if entry.get('transcript') else ''
        subtitle_note = '<p>本地文件模式下字幕可能受浏览器限制，可下载字幕查看。</p>' if entry.get('captions_href') else ''
        cards.append('<article id="asset-{id}"><h2>{title}</h2><p>{kind} · {size:,} 字节</p>{media}{caption}{transcript}{note}<div class="actions"><a href="{open_href}" target="_blank" rel="noopener noreferrer">{open_label}</a><a href="{href}" download>下载副本</a></div><code>{href}</code></article>'.format(id=entry['id'], title=title, kind=esc(entry['kind']), size=entry['size'], media=media, caption=caption, transcript=transcript, note=subtitle_note, href=href, open_href=open_href, open_label=open_label))
    for link in manifest['links']:
        cards.append('<article id="link-{}"><h2>{}</h2><p>外部链接 · 需要联网，可能要求登录</p><a href="{}" target="_blank" rel="noopener noreferrer">访问链接</a></article>'.format(link['id'], esc(link['title']), esc(link['url'], quote=True)))
    title = esc(manifest['title'])
    return '''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>''' + title + ''' · 相关资料</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6fb;color:#182334;font:16px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}
main{max-width:1040px;margin:auto;padding:48px 24px}h1{font-size:clamp(28px,4vw,44px)}h2{font-size:21px}p{color:#566477}a{color:#245ad9;text-underline-offset:4px}
article{padding:24px;margin:20px 0;background:white;border:1px solid #d5deec;border-radius:16px;overflow-wrap:anywhere}
img,video{display:block;max-width:100%;height:auto;max-height:70vh;object-fit:contain}audio{max-width:100%;width:100%}.actions{display:flex;gap:20px;flex-wrap:wrap}
a,summary{display:inline-block;min-height:44px;padding-block:8px}code{display:block;overflow-wrap:anywhere;color:#566477;font-size:12px}
:focus-visible{outline:3px solid #245ad9;outline-offset:3px}@media(max-width:600px){main{padding:24px 16px}article{padding:18px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media print{body,article{background:white;color:black}article{break-inside:avoid}video,audio{display:none}img{max-height:100mm}details{display:block}}
</style></head><body><main><h1>''' + title + ''' · 相关资料</h1>
<p>以下文件已随网页打包。请完整解压后打开；PDF/图片可能直接显示，Office/ZIP 通常需下载后用本地应用打开。</p>
''' + ('\n'.join(cards) if cards else '<p>尚未选择交付素材。将文件放入 materials，并告诉助手如何使用。</p>') + '\n</main></body></html>\n'


def text_preview(title, content, original_href):
    esc = html.escape
    return '''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>''' + esc(title) + ''' · 文本预览</title><style>
body{margin:0;color:#182334;background:#f3f6fb;font:16px/1.8 -apple-system,"PingFang SC",sans-serif}
main{max-width:1000px;margin:auto;padding:32px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:24px}a{display:inline-block;padding:10px;color:#245ad9;min-height:24px}
:focus-visible{outline:3px solid #245ad9}@media(max-width:600px){main{padding:16px}pre{padding:16px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important}}@media print{body{background:white}nav{display:none}}
</style></head><body><main><h1>''' + esc(title) + '''</h1><p>按 UTF-8 显示的纯文本预览，原件未改写；代码和标记只作文本展示。</p>
<nav><a href="../resources.html">返回资料页</a><a href="../''' + esc(original_href, quote=True) + '''" download>下载原件</a></nav><pre>''' + esc(content) + '</pre></main></body></html>\n'


def version_name(value):
    if not re.fullmatch(r'v\d{3}', value) or value == 'v000':
        fail('版本必须是 v001 至 v999。')
    return value


def prepare_project(root, version):
    config = load_project(root)
    planned = plan_resources(root, config)
    version_name(version)
    output = local_path(root, 'dist/' + version, must_exist=False)
    if output.exists():
        fail('版本目录已存在，未做任何覆盖；请选择新版本。')
    mime_types = {'.mp4': 'video/mp4', '.webm': 'video/webm', '.mp3': 'audio/mpeg',
                  '.wav': 'audio/wav', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4'}
    public = []
    for entry in planned:
        path, item = entry['path'], entry['item']
        digest = file_hash(path)
        if path.stat().st_size != entry['size']:
            fail('选材后文件大小发生变化，请重新准备。')
        folder = 'files' if entry['kind'] == 'captions' else entry['kind']
        href = 'assets/{}/{}--{}{}'.format(folder, item['id'], digest[:12], path.suffix.lower())
        data = {key: item[key] for key in ('id', 'title', 'alt', 'caption', 'section', 'transcript') if key in item}
        data.update(href=href, sha256=digest, size=entry['size'], kind=entry['kind'], use=entry['use'],
                    mime=mime_types.get(path.suffix.lower(), 'application/octet-stream'))
        public.append(data)
    text_pages = {}
    for entry, data in zip(planned, public):
        if entry['path'].suffix.lower() in {'.txt', '.md', '.csv', '.json', '.vtt', '.srt'} and entry['size'] <= 1024 ** 2:
            raw = entry['path'].read_bytes()
            if hashlib.sha256(raw).hexdigest() != data['sha256']:
                fail('生成文本预览时素材发生变化。')
            try:
                content = raw.decode('utf-8-sig')
            except UnicodeError:
                continue
            data['preview_href'] = 'previews/{}.html'.format(data['id'])
            text_pages[data['preview_href']] = text_preview(data['title'], content, data['href'])
    by_id = {entry['id']: entry for entry in public}
    for entry, data in zip(planned, public):
        for field in ('poster', 'captions'):
            if field + '_id' in entry['item']:
                data[field + '_href'] = by_id[entry['item'][field + '_id']]['href']
    manifest = {'schema_version': 1, 'slug': config['slug'], 'title': config['title'],
                'version': version, 'resources': public, 'links': config['links']}
    if len(json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')) >= 1024 ** 2:
        fail('公开素材清单超过 1 MiB，请减少长文转录或拆分项目。')
    output.mkdir(parents=True, exist_ok=False)
    for entry, data in zip(planned, public):
        source = local_path(root, entry['item']['path'])
        target = local_path(output, data['href'], must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        copy_checked(source, target, data['sha256'])
    for relative, source in text_pages.items():
        target = local_path(output, relative, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as stream:
            stream.write(source)
    write_json(output / 'manifest.json', manifest)
    with (output / 'resources.html').open('x', encoding='utf-8') as stream:
        stream.write(resource_page(manifest))
    return {'output': str(output), 'resources': len(public), 'links': len(config['links']),
            'message': '素材准备完成；resources.html 可直接打开。请由助手继续生成 index.html。'}


def package_files(output):
    result = []
    def walk_error(error):
        raise error
    for current, dirs, files in os.walk(output, followlinks=False, onerror=walk_error):
        for name in dirs + files:
            path = Path(current) / name
            if path.is_symlink() or blocked(name):
                fail('包内含隐藏/敏感文件或符号链接：{}'.format(name))
        for name in files:
            path = Path(current) / name
            if not path.is_file():
                fail('包内存在非普通文件。')
            result.append(path)
            if len(result) > MAX_ITEMS * 2 + 100:
                fail('包内文件数量过大。')
    return sorted(result)


def pack_project(root, version):
    config = load_project(root)
    version_name(version)
    output = local_path(root, 'dist/' + version, must_exist=False)
    local_path(output, 'index.html')
    manifest = load_json(local_path(output, 'manifest.json'))
    if not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'slug', 'title', 'version', 'resources', 'links'}:
        fail('manifest 结构不符合契约。')
    if manifest.get('schema_version') != 1 or manifest.get('slug') != config['slug'] or manifest.get('version') != version:
        fail('manifest 与项目/版本不匹配。')
    if not isinstance(manifest['resources'], list) or len(manifest['resources']) > MAX_ITEMS:
        fail('manifest.resources 不是有效数组。')
    if not isinstance(manifest['links'], list) or len(manifest['links']) > MAX_ITEMS:
        fail('manifest.links 不是有效数组。')
    for link in named_items(manifest['links'], 'links', {'id', 'title', 'url', 'section'}).values():
        external_url(link.get('url'))
    public_fields = {'id', 'title', 'alt', 'caption', 'section', 'transcript', 'href', 'sha256', 'size', 'kind', 'use', 'mime', 'poster_href', 'captions_href', 'preview_href'}
    entries = named_items(manifest['resources'], 'manifest.resources', public_fields)
    assets = {}
    for entry in entries.values():
        href = text(entry.get('href'), 'href', True)
        digest = text(entry.get('sha256'), 'sha256', True)
        if not re.fullmatch(r'[a-f0-9]{64}', digest) or type(entry.get('size')) is not int or not 0 <= entry['size'] <= MAX_FILE:
            fail('manifest 校验值或大小错误。')
        suffix = Path(href).suffix
        kind = entry.get('kind')
        if not isinstance(kind, str) or suffix not in KINDS.get(kind, set()) or entry.get('use') not in ('embed', 'attachment'):
            fail('manifest 包含不支持交付的素材类型。')
        folder = 'files' if kind == 'captions' else kind
        if href != 'assets/{}/{}--{}{}'.format(folder, entry['id'], digest[:12], suffix):
            fail('manifest 资产名称与内容指纹不一致。')
        if not re.fullmatch(r'assets/(images|videos|audio|files)/' + ID_PATTERN + r'--[a-f0-9]{12}\.[a-z0-9]+', href):
            fail('manifest 中的资产命名不符合契约。')
        path = local_path(output, href)
        if href in assets or path.stat().st_size != entry['size'] or file_hash(path) != entry['sha256']:
            fail('资产重复或内容与 manifest 不一致：{}'.format(href))
        assets[href] = entry
        if 'preview_href' in entry:
            if entry['preview_href'] != 'previews/{}.html'.format(entry['id']):
                fail('文本预览路径不符合契约。')
            local_path(output, entry['preview_href'])
    paths = package_files(output)
    if sum(path.stat().st_size for path in paths) > MAX_TOTAL + 20 * 1024 ** 2:
        fail('包体积超过限制。')
    warnings = []
    for path in paths:
        relative = path.relative_to(output).as_posix()
        if relative in assets or relative == 'manifest.json':
            continue
        if path.suffix.lower() != '.html' or relative.startswith('assets/'):
            fail('发现未选定或非预期文件：{}'.format(relative))
        if path.stat().st_size > 20 * 1024 ** 2:
            fail('单个 HTML 超过 20 MiB，请检查内嵌资源。')
        source = path.read_text(encoding='utf-8-sig')
        if str(root) in source:
            fail('页面包含本机项目绝对路径：{}'.format(relative))
        errors, notes = validate(source, path.parent, package_root=output)
        if errors:
            fail('{} 检查失败：{}'.format(relative, '；'.join(errors)))
        warnings.extend(notes)
    archive = local_path(root, 'dist/{}-{}.zip'.format(config['slug'], version), must_exist=False)
    with zipfile.ZipFile(archive, mode='x', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
        for path in paths:
            before = fingerprint(path)
            relative = path.relative_to(output).as_posix()
            bundle.write(path, '{}/{}'.format(config['slug'] + '-' + version, relative))
            if before != fingerprint(path) or (relative in assets and file_hash(path) != assets[relative]['sha256']):
                fail('打包期间文件变化，ZIP 不完整，请勿交付。')
    return {'archive': str(archive), 'files': len(paths), 'warnings': sorted(set(warnings)),
            'message': '完整解压后打开 index.html；媒体实际播放仍需浏览器验收。'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'scan', 'prepare', 'pack'):
        command = commands.add_parser(name)
        command.add_argument('project', type=Path)
        if name == 'init':
            command.add_argument('--title', default='我的内容网页')
        if name in ('prepare', 'pack'):
            command.add_argument('--version', default='v001')
    args = parser.parse_args(argv)
    try:
        root = project_root(args.project)
        if args.command == 'init':
            result = init_project(root, args.title)
        elif args.command == 'scan':
            result = scan_project(root)
        elif args.command == 'prepare':
            result = prepare_project(root, args.version)
        else:
            result = pack_project(root, args.version)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('操作失败：{}\n原件未被修改；若已开始复制，请检查并保留未完成版本，不要直接分享。'.format(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
