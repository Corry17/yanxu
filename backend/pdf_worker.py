"""有时间/页数/像素上限的独立 PDF 解析进程。"""
import json
from pathlib import Path
import resource
import sys
import pdfplumber
import pypdfium2 as pdfium


def extract(source, output):
    resource.setrlimit(resource.RLIMIT_CPU, (60, 65))
    resource.setrlimit(resource.RLIMIT_FSIZE, (30 * 1024 * 1024, 30 * 1024 * 1024))
    document = pdfium.PdfDocument(source)
    if len(document) > 80:
        raise ValueError('PDF 超过 80 页，请拆分后导入')
    pages = []
    with pdfplumber.open(source) as pdf:
        for i, page in enumerate(pdf.pages):
            width, height = document[i].get_size()
            scale = min(1.4, 1400 / max(width, height))
            filename = f'page-{i + 1}.png'
            document[i].render(scale=scale).to_pil().save(output / filename)
            text = page.extract_text() or ''
            if len(text) > 50000:
                raise ValueError('单页文本异常过大')
            pages.append({'number': i + 1, 'text': text, 'image': filename})
    document.close()
    return {'pages': pages}


if __name__ == '__main__':
    print(json.dumps(extract(sys.argv[1], Path(sys.argv[2])), ensure_ascii=False))
