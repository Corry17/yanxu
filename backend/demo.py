"""可选教学数据；所有数值均标识为合成示例，不是科研成果。"""
import hashlib
import io
import json
from PIL import Image, ImageDraw
from .domain import Project, Reading
from .experiments import verify_log
from .store import identifier


def create_demo(store):
    id = identifier('project')
    project = Project(title='理解注意力，建立可复现实验', question='缩放因子如何影响注意力分布，怎样通过对照实验验证？',
                      baseline='Scaled dot-product attention · 教学实现', bottleneck='从公式理解走到可核验的实现，尚未开展真实训练。',
                      goals='读清一个公式，追踪 tensor shape，设计单变量对照。',
                      constraints='教学示例；所有曲线来自合成日志，不用于科研结论。', demo=True)
    store.put('project', id, project.model_dump(), id=id)
    paper = store.put('paper', id, dict(title='Scaled Dot-Product Attention · 教学材料', access='teaching',
                      abstract='本材料用于展示公式、图片、代码的关联阅读，不是对某篇论文全文的核验。',
                      status='reading', reason='从最小可理解单元开始，演示科研阅读工作流。',
                      canonical='teaching:attention', demo=True))
    image = Image.new('RGB', (1280, 300), '#f4f6f8')
    draw = ImageDraw.Draw(image)
    blocks = [('1. Q @ K.T', 'similarity'), ('2. / sqrt(d_k)', 'scale'), ('3. softmax', 'distribution'), ('4. @ V', 'aggregation')]
    for i, (title, sub) in enumerate(blocks):
        x = 35 + i * 310
        draw.rounded_rectangle((x, 80, x + 275, 220), radius=12, fill='white', outline='#9eafb4', width=2)
        draw.text((x + 40, 120), title, fill='#285f64', font_size=22)
        draw.text((x + 40, 165), sub, fill='#63707f', font_size=17)
        if i < 3:
            draw.line((x + 276, 150, x + 305, 150), fill='#285f64', width=3)
            draw.polygon([(x + 305, 150), (x + 297, 145), (x + 297, 155)], fill='#285f64')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    asset = store.save_blob(buffer.getvalue(), '.png')
    reading = Reading(title='从相似度到信息聚合：拆解一个注意力公式', paper_id=paper['id'], refs=[{'id': paper['id'], 'version': 1}],
        summary='注意力先比较 Query 和 Key，再用归一化权重聚合 Value；缩放影响 softmax 输入的数值范围。',
        motivation='先回答“每一项在做什么”，再考虑是否需要改动算法。这个示例演示讲解结构，不替代原论文阅读。',
        contribution=['把复杂方法缩小到一个数学操作链。', '明确每一步的 tensor shape，连接公式和代码。'],
        formulas=[dict(title='缩放点积注意力', latex=r'\operatorname{Attention}(Q,K,V)=\operatorname{softmax}\left(\frac{QK^{\mathsf{T}}}{\sqrt{d_k}}\right)V',
            number='教学式 A', source='人工编写的基础教学示例；未绑定论文页码。', derivation='teaching', reviewed=False,
            symbols=[dict(symbol='Q', meaning='Query：当前查询表示', shape='n × d_k'),
                     dict(symbol='K', meaning='Key：用于匹配的表示', shape='m × d_k'),
                     dict(symbol='V', meaning='Value：被聚合的信息', shape='m × d_v'),
                     dict(symbol='d_k', meaning='Query/Key 的特征维度', shape='正整数')],
            steps=['相似度：Q 与 K 的转置相乘，得到 n × m 的配对分数。',
                   '缩放：除以 √d_k，控制进入 softmax 的分数量级。',
                   '归一化：沿 Key 维应用 softmax，每个 Query 的权重和为 1。',
                   '聚合：权重乘以 V，输出 n × d_v 的表示。'],
            terms=[r'QK^{\mathsf{T}}', r'\frac{QK^{\mathsf{T}}}{\sqrt{d_k}}', r'A=\operatorname{softmax}(S)', r'AV'],
            intuition='可以把它理解为“先决定看哪里，再汇总看到的内容”。',
            limitation='这是标准非掩码单头形式；批次、多头、mask、dropout 和数值稳定性需要另外解释。')],
        figures=[dict(title='四步数据流 · 辅助教学图', asset=asset, caption='从相似度、缩放、归一化到 Value 聚合。',
            source='本工作台绘制的教学示意图，非论文原图。', kind='teaching',
            regions=[dict(label=b[0], explanation=e, box=[(35 + i * 310) / 1280, 80 / 300, 275 / 1280, 140 / 300])
                     for i, (b, e) in enumerate(zip(blocks, ['输入 Q/K；输出配对相似度矩阵。', '此处是对照实验可以控制的单一变量。', '按 Key 维归一化，不是对整张矩阵一起归一化。', '输出维度由 Query 数量和 Value 特征维度决定。']))],
            takeaway='图中的四个区域分别对应公式的四个计算步骤。')],
        code=[dict(title='最小教学实现', code='scores = q @ k.transpose(-2, -1)\nscaled = scores / math.sqrt(q.size(-1))\nweights = torch.softmax(scaled, dim=-1)\noutput = weights @ v',
                   location='教学伪代码 · 非仓库运行证据', status='teaching',
                   explanation=['最后两维分别是序列长度与特征维度。', 'softmax 的 dim=-1 对应 Key 维。', '这里不含 mask、dropout 和混合精度处理。'], formula='依次对应：相似度 → 缩放 → 归一化 → 聚合。')],
        limitations=['尚未导入论文原文，不能引用具体页码、公式编号或作者实验结论。', '未运行真实训练，不能证明任何任务上的收益。'],
        next_steps=['导入真实 PDF 并核对公式。', '固定数据与实现，预注册是否使用缩放的对照实验。'], demo=True)
    store.put('reading', id, reading.model_dump())
    log = '\n'.join([json.dumps({'type': 'health', 'healthy': True})] + [json.dumps({
        'type': 'metric', 'metric': 'synthetic_loss', 'split': 'val', 'seed': seed, 'step': step,
        'value': round(0.9 / (step + 1) + offset, 4)}) for seed, offset in [(42, .02), (123, .04), (2026, .03)] for step in range(1, 7)])
    blob = store.save_blob(log.encode(), '.jsonl')
    result = verify_log(log)
    store.put('run', id, result | dict(title='合成日志解析示例 · 非真实训练', blob=blob, log_hash=hashlib.sha256(log.encode()).hexdigest(),
              protocol='纯合成数值，用于展示日志来源、seed 和曲线；未运行算法实验。',
              demo=True, status='imported', refs=[]))
    store.put('note', id, dict(title='已明确公式到实现的对应关系', category='progress',
              text='教学演示：已拆分四个计算步骤；下一步需要真实论文和代码证据。',
              refs=[{'id': paper['id'], 'version': 1}], reviewed=False, visibility='dev'))
    store.put('note', id, dict(title='还缺真实实验协议', category='blocker',
              text='需要确定数据划分、主要指标和远程环境后，才能提交实验审批。', refs=[], reviewed=False, visibility='dev'))
    return store.get(id)
