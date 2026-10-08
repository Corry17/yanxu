#!/usr/bin/env python3
"""离线内容网页的静态启发式检查；核对媒体与本地直链，不执行脚本。"""

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.ids = set()
        self.duplicates = set()
        self.title_parts = []
        self.styles = []
        self.scripts = []
        self.active = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        identifier = attrs.get('id')
        if identifier:
            if identifier in self.ids:
                self.duplicates.add(identifier)
            self.ids.add(identifier)
        if tag in ('title', 'style', 'script'):
            self.active = tag

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.active == tag:
            self.active = None

    def handle_data(self, data):
        if self.active == 'title':
            self.title_parts.append(data)
        elif self.active == 'style':
            self.styles.append(data)
        elif self.active == 'script':
            self.scripts.append(data)


def validate(source, base=None, preview=False, allow_external=False, package_root=None):
    """返回 (错误, 警告)；base 为 HTML 目录，package_root 为可移交包边界。"""
    errors, warnings = [], []
    parser = DocumentParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as exc:
        return ['无法解析 HTML：{}'.format(exc)], warnings

    def require(condition, message):
        if not condition:
            errors.append(message)

    require(bool(re.match(r'\s*<!doctype\s+html\s*>', source, re.I)), '缺少 HTML5 doctype。')
    html_tags = [attrs for tag, attrs in parser.tags if tag == 'html']
    require(len(html_tags) == 1, '需要且只能有一个 html 根元素。')
    require(bool(html_tags and html_tags[0].get('lang')), 'html 缺少 lang。')
    require(bool(''.join(parser.title_parts).strip()), '缺少有效的文档 title。')
    require(sum(tag == 'body' for tag, _ in parser.tags) == 1, '需要且只能有一个 body。')
    require(any(tag == 'main' for tag, _ in parser.tags), '缺少 main 正文区域。')
    require(sum(tag == 'h1' for tag, _ in parser.tags) == 1, '需要且只能有一个 H1。')
    require(bool(re.search(r'</html>\s*$', source, re.I)), '文档结尾不完整。')
    metas = [attrs for tag, attrs in parser.tags if tag == 'meta']
    require(any(attrs.get('charset', '').lower() == 'utf-8' for attrs in metas), '缺少 UTF-8 charset。')
    viewport = next((attrs.get('content', '') for attrs in metas if attrs.get('name', '').lower() == 'viewport'), '')
    normalized_viewport = re.sub(r'\s+', '', viewport.lower())
    require('width=device-width' in normalized_viewport, 'viewport 缺少 width=device-width。')
    require(not re.search(r'user-scalable=(no|0)(?:,|$)', normalized_viewport), '不能禁止用户缩放。')
    max_scale = re.search(r'maximum-scale=([\d.]+)', normalized_viewport)
    if max_scale:
        try:
            require(float(max_scale.group(1)) >= 2, 'maximum-scale 过小，妨碍放大阅读。')
        except ValueError:
            errors.append('maximum-scale 格式错误。')
    for identifier in sorted(parser.duplicates):
        errors.append('重复的 id：{}'.format(identifier))

    def check_resource(value, hyperlink=False):
        value = value.strip()
        if not value or value == '#':
            errors.append('存在空资源或占位链接。')
            return
        if any(ord(char) < 32 or ord(char) == 127 for char in value) or '\\' in value:
            errors.append('URL 含控制字符或反斜杠。')
            return
        try:
            parsed = urlsplit(value)
            parsed.port
        except ValueError:
            errors.append('URL 格式错误。')
            return
        if value.startswith('#'):
            return
        if parsed.scheme == 'data':
            if hyperlink or not re.match(r'data:image/(?:png|jpeg|gif|webp|avif);base64,', value, re.I):
                errors.append('仅接受静态位图 data 资源；超链接不接受 data 协议。')
            return
        if parsed.scheme or parsed.netloc:
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
                errors.append('非便携或不安全 URL：只允许 HTTP(S) 或包内相对链接。')
                return
            if not hyperlink:
                message = '发现非内联资源：{}'.format(value[:100])
                (warnings if allow_external else errors).append(message)
            return
        decoded = unquote(parsed.path)
        if value.startswith('/') or decoded.startswith('/') or '\\' in decoded or ':' in decoded or '\x00' in decoded:
            errors.append('绝对路径或非法本地 URL 无法便携打开。')
            return
        if base is None:
            warnings.append('未提供 HTML 目录，本地资源尚未核对：{}'.format(value[:100]))
            return
        root = Path(package_root if package_root is not None else base).resolve()
        candidate = Path(base).absolute()
        for part in Path(decoded).parts:
            candidate = candidate / part
            if candidate.is_symlink():
                errors.append('本地资源不能经过符号链接：{}'.format(value[:100]))
                return
        path = candidate.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append('本地资源越出交付包：{}'.format(value[:100]))
            return
        if not path.is_file():
            errors.append('本地资源不存在：{}'.format(value[:100]))
        else:
            warnings.append('包含配套资源，分享时需一起提供：{}'.format(value[:100]))

    for tag, attrs in parser.tags:
        if not preview and ('data-preview-only' in attrs or 'data-demo-content' in attrs):
            errors.append('成品仍包含预览/示例标记。')
        if not preview and attrs.get('id') == 'preview-script':
            errors.append('成品仍包含样式预览脚本。')
        if tag in ('iframe', 'object', 'embed', 'base') or 'srcdoc' in attrs:
            errors.append('离线内容页不应携带活动嵌入或 base 元素：{}'.format(tag))
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh':
            errors.append('不能自动跳转页面。')
        if tag == 'img' and 'alt' not in attrs:
            errors.append('图片缺少 alt。')
        if tag in ('img', 'source', 'track') and not attrs.get('src'):
            errors.append('{} 缺少实际 src。'.format(tag))
        if tag in ('video', 'audio'):
            require('controls' in attrs, '视频/音频缺少 controls。')
            if 'autoplay' in attrs:
                warnings.append('媒体会自动播放，请核实是否为用户明确要求。')
        if tag == 'video' and 'playsinline' not in attrs:
            warnings.append('视频缺少 playsinline，请检查手机播放行为。')
        for key, value in attrs.items():
            if key.startswith('on'):
                errors.append('发现内联事件处理器：{}'.format(key))
            if key in ('href', 'src', 'action', 'formaction', 'xlink:href'):
                compact = re.sub(r'[\x00-\x20\x7f]+', '', value or '').lower()
                if compact.startswith(('javascript:', 'vbscript:', 'data:text/html', 'data:application/')):
                    errors.append('发现可执行或不安全 URL。')
        if tag == 'a' and 'href' in attrs:
            href = attrs.get('href', '').strip()
            check_resource(href, hyperlink=True)
            if href.startswith('#') and href != '#':
                if unquote(href[1:]) not in parser.ids:
                    errors.append('锚点不存在：{}'.format(href))
            if attrs.get('target', '').lower() == '_blank':
                require({'noopener', 'noreferrer'}.issubset(set(attrs.get('rel', '').lower().split())), '新窗口链接缺少 noopener noreferrer。')
        if tag in ('img', 'script', 'audio', 'video', 'source', 'track', 'input') and attrs.get('src'):
            check_resource(attrs['src'])
        if attrs.get('poster'):
            check_resource(attrs['poster'])
        if attrs.get('srcset'):
            errors.append('请逐项检查 srcset；当前检查器要求改用明确的 src。')
        if tag == 'link' and attrs.get('href'):
            check_resource(attrs['href'])
        if attrs.get('style'):
            parser.styles.append(attrs['style'])

    css = '\n'.join(parser.styles)
    scripts = '\n'.join(parser.scripts)
    require('@media' in css and 'print' in css, '缺少打印样式。')
    require('prefers-reduced-motion' in css, '缺少减少动态效果的适配。')
    require(bool(re.search(r'@media[^{}]*(?:max|min)-width', css)), '缺少窄屏适配。')
    require(':focus-visible' in css or ':focus' in css, '缺少键盘焦点样式。')
    for match in re.finditer(r'url\(\s*[\"\']?([^\)\"\']+)[\"\']?\s*\)', css, re.I):
        check_resource(match.group(1))
    if re.search(r'@import\b', css, re.I):
        errors.append('请将 CSS 内联，不能依赖 @import。')
    if re.search(r'\beval\s*\(|\bnew\s+Function\s*\(|document\s*\.\s*write\s*\(', scripts):
        errors.append('发现动态执行或 document.write。')
    if re.search(r'\.innerHTML\s*\+?=|\.outerHTML\s*\+?=|\.insertAdjacentHTML\s*\(', scripts):
        warnings.append('发现 HTML 字符串写入，请人工检查输入来源和转义。')
    if re.search(r'\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bsendBeacon\s*\(', scripts):
        (warnings if allow_external else errors).append('脚本存在网络调用，需要检查离线能力与数据外发。')
    for marker in ('mainsite_server_content', 'ssr_frontend_data', 'WSM_config'):
        if marker in source:
            errors.append('疑似包含平台外壳：{}'.format(marker))
    if re.search(r'\{\{[^{}\n]+\}\}|\bTODO\b|\bPLACEHOLDER\b', source):
        warnings.append('发现可能的未替换占位符，请人工确认是否属于被展示的代码。')
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))


def main(argv=None):
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument('html', type=Path, help='要检查的 HTML 文件')
    arg_parser.add_argument('--preview', action='store_true', help='允许样式预览和示例标记')
    arg_parser.add_argument('--package-root', type=Path, help='交付包根目录；子页引用必须留在包内')
    arg_parser.add_argument('--allow-external', action='store_true', help='允许已告知用户的联网依赖，仍输出警告')
    args = arg_parser.parse_args(argv)
    try:
        if args.html.suffix.lower() not in ('.html', '.htm'):
            raise ValueError('输入必须是 .html 或 .htm 文件。')
        if args.html.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('文件超过 20 MiB，请先检查是否包含不必要的内嵌资源。')
        source = args.html.read_text(encoding='utf-8-sig')
        if args.package_root:
            args.html.resolve().relative_to(args.package_root.resolve())
        errors, warnings = validate(source, args.html.resolve().parent, args.preview, args.allow_external, args.package_root)
    except (OSError, UnicodeError, ValueError) as exc:
        print('读取/检查失败：{}'.format(exc), file=sys.stderr)
        return 2
    for warning in warnings:
        print('警告：{}'.format(warning))
    for error in errors:
        print('错误：{}'.format(error))
    if errors:
        print('未通过：{} 项错误。'.format(len(errors)))
        return 1
    print('通过静态检查（{} 项警告）。仍需浏览器和内容核对。'.format(len(warnings)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
