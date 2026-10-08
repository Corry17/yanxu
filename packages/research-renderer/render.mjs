import { mathjax } from "mathjax-full/js/mathjax.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import { SVG } from "mathjax-full/js/output/svg.js";
import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import "mathjax-full/js/input/tex/ams/AmsConfiguration.js";
import { pathToFileURL } from "node:url";

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const math = mathjax.document("", {
  InputJax: new TeX({
    packages: ["base", "ams"],
    maxBuffer: 14000,
    maxMacros: 1000,
  }),
  OutputJax: new SVG({ fontCache: "none" }),
});
export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        ch
      ],
  );
export function equation(latex) {
  if (
    typeof latex !== "string" ||
    latex.length > 12000 ||
    /\\(?:href|url|html|style|class|cssId|includegraphics|require|def|newcommand)\b/.test(
      latex,
    )
  )
    throw new Error("公式含不支持的活动指令或超过长度限制");
  const output = adaptor.outerHTML(math.convert(latex, { display: true }));
  if (
    /data-mjx-error|<merror|foreignObject|<script|\son\w+=|(?:href|src)\s*=\s*["'](?!#)/i.test(
      output,
    )
  )
    throw new Error("公式无法可靠渲染，请核对 LaTeX");
  return output;
}
const list = (items = []) =>
  `<ul>${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
const para = (text) => `<p>${esc(text)}</p>`;
const badge = (text) => `<span class="badge">${esc(text)}</span>`;
const source = (text) => `<p class="source">来源 · ${esc(text)}</p>`;
function formula(item, i) {
  return `<article class="formula-unit" id="formula-${i}"><header>${badge(item.reviewed ? "已人工核对" : "转录待核对")} ${badge(item.derivation === "source" ? "原文推导" : "辅助教学解释")}<h3>${esc(item.title)} ${esc(item.number)}</h3></header>
  <div class="equation">${equation(item.latex)}</div><div class="formula-terms">${(item.terms || []).map((t, j) => `<div data-term="${j}">${equation(t)}<small>步骤 ${j + 1}</small></div>`).join("")}</div>${source(item.source)}${item.asset ? `<a href="${safeAsset(item.asset)}" target="_blank" rel="noopener noreferrer">查看公式原文页 ${esc(item.page || "")}</a>` : ""}
  <details><summary>复制 LaTeX / 对照原始转录</summary><pre>${esc(item.latex)}</pre></details>
  <div class="explain-grid"><div><h4>先认清每一个符号</h4><table><thead><tr><th>符号</th><th>含义</th><th>维度 / 单位</th></tr></thead><tbody>${(item.symbols || []).map((s) => `<tr><td><code>${esc(s.symbol)}</code></td><td>${esc(s.meaning)}</td><td>${esc(s.shape)}</td></tr>`).join("")}</tbody></table></div>
  <div><h4>一步一步理解</h4><ol class="steps">${(item.steps || []).map((s, j) => `<li><button class="step" data-step="${j}"><b>0${j + 1}</b><span>${esc(s)}</span></button></li>`).join("")}</ol></div></div>
  ${para(item.intuition)}<aside>适用边界：${esc(item.limitation || "尚未补充，不能据此推广结论。")}</aside></article>`;
}
function safeAsset(asset) {
  if (!/^assets\/(images|files)\/[a-z0-9-]+\.[a-z0-9]+$/.test(asset))
    throw new Error("素材路径必须来自已核对 manifest");
  return asset;
}
function figure(item, i) {
  return `<article class="figure-unit" id="figure-${i}"><h3>${esc(item.title)}</h3>${badge(item.kind === "teaching" ? "辅助教学图" : item.kind === "crop" ? "原图裁剪" : "来源原图")}
  ${item.asset ? `<figure><a href="${safeAsset(item.asset)}" target="_blank" rel="noopener noreferrer"><img src="${safeAsset(item.asset)}" alt="${esc(item.caption)}"></a><figcaption>${esc(item.caption)} · 点击打开原图</figcaption></figure>` : '<p class="source">没有原图素材；以下仅是文字结构说明，不声称已读图。</p>'}
  <ol class="regions">${(item.regions || []).map((r, j) => `<li><b>${j + 1}. ${esc(r.label)}</b>${r.crop ? `<figure><img src="${safeAsset(r.crop)}" alt="${esc(r.label)} · 原图局部裁剪"><figcaption>局部放大；请结合上方整图阅读。</figcaption></figure>` : ""}${para(r.explanation)}</li>`).join("")}</ol>${para(item.takeaway)}${source(item.source)}</article>`;
}
function code(item) {
  return `<article><h3>${esc(item.title)}</h3>${badge(item.status === "executed" ? "有运行证据" : item.status === "teaching" ? "教学伪代码" : "静态分析")}<p class="source">${esc(item.location)}</p><div class="explain-grid"><pre><code>${esc(item.code)}</code></pre><div><h4>从数学到实现</h4>${list(item.explanation)}${para(item.formula)}</div></div></article>`;
}
function reading(content, sectionId) {
  return `<h2>为什么值得读</h2>${para(content.motivation)}<aside>${esc(content.summary)}</aside><h3>问题与贡献</h3>${list(content.contribution)}
  ${(content.formulas || []).length ? "<h2>把方法拆成可理解的公式</h2>" + content.formulas.map((f, i) => formula(f, `${sectionId}-${i}`)).join("") : "<p>尚无经核对的公式讲解。</p>"}
  ${(content.figures || []).length ? "<h2>从整图读到局部</h2>" + content.figures.map((f, i) => figure(f, `${sectionId}-${i}`)).join("") : ""}
  ${(content.code || []).length ? "<h2>实现对应</h2>" + content.code.map(code).join("") : ""}
  <h2>局限与下一步</h2>${list(content.limitations)}${list(content.next_steps)}`;
}
function curves(metrics = []) {
  const groups = new Map();
  for (const m of metrics) {
    const key = `${m.split} / ${m.metric}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(m);
  }
  return [...groups.entries()]
    .map(([key, points]) => {
      const xs = points.map((p) => p.step),
        ys = points.map((p) => p.value);
      const minX = Math.min(...xs),
        maxX = Math.max(...xs),
        minY = Math.min(...ys),
        maxY = Math.max(...ys);
      const seeds = [...new Set(points.map((p) => p.seed))],
        colors = ["#286c60", "#5676b0", "#b08849", "#9b6b93"];
      const lines = seeds
        .map(
          (seed, i) =>
            `<polyline fill="none" stroke="${colors[i % colors.length]}" stroke-width="2" points="${points
              .filter((p) => p.seed === seed)
              .sort((a, b) => a.step - b.step)
              .map(
                (p) =>
                  `${60 + ((p.step - minX) / (maxX - minX || 1)) * 560},${205 - ((p.value - minY) / (maxY - minY || 1)) * 160}`,
              )
              .join(" ")}"/>`,
        )
        .join("");
      const ticks = Array.from(
        { length: 5 },
        (_, i) =>
          `<line x1="60" x2="620" y1="${45 + i * 40}" y2="${45 + i * 40}" stroke="#e0e6e3"/><text x="52" y="${49 + i * 40}" text-anchor="end" font-size="10">${(maxY - ((maxY - minY) * i) / 4).toFixed(3)}</text>`,
      ).join("");
      return `<figure><h4>${esc(key)}</h4><svg viewBox="0 0 660 250" role="img" aria-label="${esc(key)} 原始日志曲线"><title>${esc(key)}，横轴 step，纵轴日志值</title>${ticks}${lines}<text x="60" y="225" font-size="11">${esc(minX)}</text><text x="610" y="225" font-size="11">${esc(maxX)}</text><text x="315" y="245" font-size="11">step</text></svg><figcaption>${seeds.map((s, i) => `<span style="color:${colors[i % colors.length]}">seed ${esc(s)}</span>`).join(" · ")}；精确值与出处见日志表，不由图形反推测量值。</figcaption></figure>`;
    })
    .join("");
}
function comparison(content) {
  return `<h2>相同协议内的实验对照</h2>${para(content.note)}${content.groups.map((g) => `<h3>${esc(g.protocol.dataset)} · ${esc(g.protocol.metric)} · ${esc(g.protocol.phase)}</h3><p class="source">${esc(g.protocol.protocol)}</p><div class="table-scroll"><table><thead><tr><th>候选</th><th>结论</th><th>有效 / 计划 seed</th><th>均值</th><th>样本标准差</th></tr></thead><tbody>${g.runs.map((r) => `<tr><td>${esc(r.title)}</td><td>${esc(r.verdict)}</td><td>${r.valid_seeds} / ${r.planned_seeds}</td><td>${r.mean === null ? "证据不足" : esc(r.mean)}</td><td>${r.std === null ? "不适用" : esc(r.std)}</td></tr>`).join("")}</tbody></table></div>`).join("")}${list(content.excluded.map((r) => `${r.title}：${r.reason}`))}`;
}
function run(content) {
  const rows = content.summaries || [];
  return `<h2>${esc(content.title)}</h2>${badge(content.verdict || "INCONCLUSIVE")}${para(content.hypothesis || "未绑定预注册假设，仅报告已有日志观察。")}
  <h3>协议与本轮改动</h3>${para(content.protocol || "协议尚未补充；不能与其他运行直接排名。")}${para(content.change || "")}
  ${curves(content.metrics || [])}<div class="table-scroll"><table><thead><tr><th>数据集</th><th>指标</th><th>seed</th><th>日志值</th><th>原日志行</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${esc(r.split)}</td><td>${esc(r.metric)}</td><td>${esc(r.seed)}</td><td>${esc(r.value)}</td><td>${esc(r.line)}</td></tr>`).join("")}</tbody></table></div>
  ${!rows.length ? "<p>没有可核验数值，不能生成结果图表。</p>" : ""}${para(content.note)}
  <h3>健康度、证据缺口与限制</h3>${list(content.problems)}${source(content.log_hash ? "原始日志 SHA256 " + content.log_hash : "用户导入/研究记录")}`;
}

export const css = `
:root{--bg:#f6f7f9;--paper:#fff;--ink:#24313e;--muted:#63707f;--line:#dce2e7;--accent:#285f64}
*{box-sizing:border-box}body{margin:0;font:16px/1.9 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:var(--ink);background:var(--bg)}
body[data-style=paper]{--bg:#f2efe7;--paper:#fcfaf5;--ink:#34372f;--muted:#77796b;--accent:#657153;--line:#deddd1}
body[data-style=lab]{--bg:#f0f3f7;--accent:#355c8a;--paper:#fff;--ink:#213448}
a{color:var(--accent);text-underline-offset:4px}button{font:inherit;cursor:pointer;color:inherit}button,summary{min-height:44px}button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.formula-terms{display:flex;flex-wrap:wrap;gap:12px}.formula-terms>div{padding:12px;overflow-x:auto;border:1px solid var(--line);border-radius:6px;flex:1;min-width:150px;text-align:center}.formula-terms>div.active{background:var(--bg);border-color:var(--accent)}.formula-terms small{color:var(--muted)}
.topbar{position:sticky;top:0;background:var(--paper);border-bottom:1px solid var(--line);z-index:3;display:flex;gap:20px;align-items:center;padding:10px 5vw}.topbar button{border:1px solid var(--line);border-radius:6px;background:transparent;padding:5px 15px}.topbar small{margin-right:auto;color:var(--muted)}
main{max-width:1100px;margin:40px auto 100px;background:var(--paper);padding:60px 65px;border:1px solid var(--line)}h1{font-size:clamp(30px,4vw,44px);line-height:1.4;margin:18px 0}h2{font-size:25px;margin:45px 0 20px;border-bottom:1px solid var(--line);padding-bottom:14px}h3{font-size:20px;margin:22px 0 14px}h4{font-size:16px}p{overflow-wrap:anywhere}.lede{font-size:18px;color:var(--muted)}.source,figcaption{font-size:13px;color:var(--muted);overflow-wrap:anywhere}.badge{font-size:12px;border:1px solid var(--line);color:var(--accent);padding:4px 9px;display:inline-block;margin:3px 7px 3px 0;border-radius:4px}.eyebrow{font:12px/1.6 monospace;letter-spacing:2px;color:var(--accent)}
article{margin:30px 0;padding-bottom:28px;border-bottom:1px solid var(--line)}.equation{padding:30px 10px;background:var(--bg);overflow-x:auto;margin:20px 0}.equation mjx-container{max-width:none}mjx-container svg{max-width:none}.explain-grid{display:grid;grid-template-columns:1fr 1fr;gap:28px;min-width:0}.explain-grid>*{min-width:0}aside{border-left:3px solid var(--accent);padding:14px 22px;background:var(--bg);margin:24px 0}.steps{list-style:none;padding:0}.step{width:100%;display:flex;gap:16px;border:0;border-bottom:1px solid var(--line);text-align:left;background:transparent;padding:16px 8px}.step b{color:var(--accent)}.step.active{background:var(--bg);box-shadow:inset 3px 0 var(--accent)}
pre{padding:20px;background:#202d39;color:#e3eaf0;font:13px/1.85 ui-monospace,monospace;overflow-x:auto;border-radius:6px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:12px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-size:12px;font-weight:500}.table-scroll{overflow:auto}figure{margin:24px 0}img{display:block;max-width:100%;height:auto;object-fit:contain}.regions{padding-left:24px}.regions li{padding:10px 0}.toc{display:flex;flex-wrap:wrap;gap:18px;margin:25px 0;padding:18px 0;border-block:1px solid var(--line)}.page{min-width:0}.footer{margin-top:40px;color:var(--muted);font-size:12px}.deck-ready .page{display:none}.deck-ready .page.current{display:block}.deck-ready main{min-height:80vh}
@media(max-width:760px){main{margin:0;border:0;padding:30px 20px}.explain-grid{grid-template-columns:1fr}.topbar{padding:8px 16px;gap:10px}.topbar small{font-size:11px}.equation{padding:20px 0}h2{font-size:22px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media print{body{background:white}.topbar,.toc{display:none}main{max-width:none;margin:0;padding:0;border:0}.deck-ready .page,.page{display:block!important;height:auto;overflow:visible;break-before:page}article,figure,.equation{break-inside:avoid}details{display:block}pre{white-space:pre-wrap;background:#f5f5f5;color:#111}.explain-grid{grid-template-columns:1fr 1fr}a{color:inherit}.source{font-size:10px}}
`;
const runtime = `
const pages=[...document.querySelectorAll('.page')];let current=0;
function show(n){current=Math.max(0,Math.min(pages.length-1,n));pages.forEach((p,i)=>p.classList.toggle('current',i===current));document.getElementById('counter').textContent=(current+1)+' / '+pages.length;}
if(document.body.dataset.mode==='deck'){document.body.classList.add('deck-ready');show(0);}else{document.querySelectorAll('[data-nav]').forEach(e=>e.hidden=true);}
document.querySelectorAll('[data-nav]').forEach(b=>b.addEventListener('click',()=>show(current+Number(b.dataset.nav))));
document.querySelectorAll('.step').forEach(b=>b.addEventListener('click',()=>{b.closest('.steps').querySelectorAll('.step').forEach(x=>x.classList.remove('active'));b.classList.add('active');b.closest('.formula-unit').querySelectorAll('[data-term]').forEach(t=>t.classList.toggle('active',t.dataset.term===b.dataset.step));}));
document.getElementById('print').addEventListener('click',()=>window.print());
document.addEventListener('keydown',e=>{if(!document.body.classList.contains('deck-ready')||e.ctrlKey||e.altKey||e.metaKey||/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||e.target.isContentEditable)return;if(e.key==='ArrowRight')show(current+1);if(e.key==='ArrowLeft')show(current-1);if(e.key==='Home')show(0);if(e.key==='End')show(pages.length-1);});
document.querySelectorAll('.toc a').forEach(a=>a.addEventListener('click',()=>{const i=pages.findIndex(p=>'#'+p.id===a.getAttribute('href'));if(i>=0)show(i);}));
`;
function sectionBody(s, i) {
  if (s.type === "reading") return reading(s.content, i);
  if (s.type === "comparison") return comparison(s.content);
  if (s.type === "run") return run(s.content);
  if (s.type === "formula") return formula(s.content, i);
  if (s.type === "figure") return figure(s.content, i);
  if (s.type === "code") return code(s.content);
  if (s.type === "code-study")
    return `<h2>${esc(s.label)}</h2>${para(s.content.summary)}${s.content.code.map(code).join("")}`;
  return `<h2>${esc(s.label)}</h2>${para(s.content.text)}${list(s.content.items)}`;
}
export function render(report) {
  const sections =
    report.mode !== "deck"
      ? report.sections
      : report.sections.flatMap((s) => {
          if (s.type !== "reading") return [s];
          const c = s.content;
          return [
            {
              type: "text",
              label: s.label + " · 问题与贡献",
              content: {
                text: c.motivation + "\n" + c.summary,
                items: c.contribution,
              },
            },
            ...(c.formulas || []).map((f) => ({
              type: "formula",
              label: f.title,
              content: f,
            })),
            ...(c.figures || []).map((f) => ({
              type: "figure",
              label: f.title,
              content: f,
            })),
            ...(c.code || []).map((f) => ({
              type: "code",
              label: f.title,
              content: f,
            })),
            {
              type: "text",
              label: "局限与下一步",
              content: {
                text: "",
                items: [...(c.limitations || []), ...(c.next_steps || [])],
              },
            },
          ];
        });
  const blocks = sections.map(
    (s, i) =>
      `<section class="page" id="section-${i}"><p class="eyebrow">${String(i + 1).padStart(2, "0")} / ${esc(s.label)}</p>${sectionBody(s, i)}</section>`,
  );
  const evidence = (report.evidence || [])
    .map(
      (e) =>
        `<li>${esc(e.title)} · ${esc(e.id)} v${esc(e.version)} · SHA256 ${esc(e.hash)}</li>`,
    )
    .join("");
  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(report.title)}</title><style>${css}</style></head><body data-style="${esc(report.style)}" data-mode="${esc(report.mode)}"><nav class="topbar"><small>RESEARCH NOTES / 科研汇报</small><button data-nav="-1">上一页</button><span id="counter" data-nav="0"></span><button data-nav="1">下一页</button><button id="print">打印 / PDF</button></nav><main><header><p class="eyebrow">${esc(report.kind)} / EVIDENCE FIRST</p>${report.demo ? badge("教学示例 · 非真实科研结果") : ""}<h1>${esc(report.title)}</h1><p class="lede">${esc(report.subtitle)}</p><p class="source">生成截点：${esc(report.created)} · ${esc(report.period || "版本化证据快照")}</p></header><nav class="toc">${sections.map((s, i) => `<a href="#section-${i}">${esc(s.label)}</a>`).join("")}</nav>${blocks.join("")}<section class="page" id="evidence"><h2>证据与原始资料</h2><ul class="source">${evidence}</ul>${report.resources ? '<a href="resources.html">打开随包资料索引</a>' : ""}<p class="footer">所有观察仅适用于所记录的条件。推断不是已验证事实；请保留原始证据与失败记录。</p></section></main><script>${runtime}</script></body></html>`;
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  let input = "";
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 8 * 1024 * 1024) throw new Error("输入过大");
  }
  const request = JSON.parse(input);
  process.stdout.write(
    request.operation === "math" ? equation(request.latex) : render(request),
  );
}
