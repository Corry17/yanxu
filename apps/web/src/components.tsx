import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  X,
  Copy,
  Check,
  FileText,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { api, fileUrl, labels, type RecordData } from "./api";

export function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={"badge " + tone}>{children}</span>;
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <FileText size={28} strokeWidth={1.3} />
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}
export function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    const before = document.activeElement as HTMLElement;
    return () => before?.focus();
  }, []);
  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button className="icon" aria-label="关闭" onClick={close}>
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function JsonEditor({
  initial,
  onSave,
  description,
}: {
  initial: any;
  onSave: (data: any) => Promise<void>;
  description: string;
}) {
  const [text, setText] = useState(JSON.stringify(initial, null, 2));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await onSave(JSON.parse(text));
        } catch (e) {
          setError(String(e));
        } finally {
          setBusy(false);
        }
      }}
    >
      <p className="muted">{description}</p>
      <textarea
        aria-label="结构化内容 JSON"
        className="json-editor"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy}>
        {busy ? "校验中…" : "校验并保存新版本"}
      </button>
    </form>
  );
}
export function MathFormula({ latex }: { latex: string }) {
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setError("");
    setSvg("");
    api("/math", "POST", { latex })
      .then((r) => {
        if (live) setSvg(r.svg);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [latex]);
  return (
    <div className="math-render" aria-label={latex}>
      {error ? (
        <div className="error">
          公式待核对：{error}
          <pre>{latex}</pre>
        </div>
      ) : svg ? (
        <div dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <code>{latex}</code>
      )}
    </div>
  );
}
export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="subtle"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1800);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}{" "}
      {copied ? "已复制" : "复制"}
    </button>
  );
}
export function FormulaExplainer({ item }: { item: any }) {
  const [step, setStep] = useState(0);
  return (
    <article className="formula-explainer">
      <div className="section-label">
        <span>FORMULA / 公式讲解</span>
        <Badge tone={item.reviewed ? "green" : "amber"}>
          {item.reviewed ? "已核对" : "转录待核对"}
        </Badge>
      </div>
      <h3>
        {item.title}
        <small>{item.number}</small>
      </h3>
      <MathFormula latex={item.latex} />
      {!!item.terms?.length && (
        <div className="formula-term-row">
          {item.terms.map((term: string, i: number) => (
            <button
              key={i}
              aria-label={`高亮第 ${i + 1} 项`}
              className={i === step ? "active" : ""}
              onClick={() => setStep(Math.min(i, item.steps.length - 1))}
            >
              <MathFormula latex={term} />
              <small>步骤 {i + 1}</small>
            </button>
          ))}
        </div>
      )}
      {item.asset && (
        <a
          className="text-link"
          href={fileUrl(item.asset)}
          target="_blank"
          rel="noreferrer"
        >
          对照公式原文页 {item.page || ""}
        </a>
      )}
      <div className="formula-source">
        <span>{item.source}</span>
        <CopyButton text={item.latex} />
      </div>
      <div className="explain-columns">
        <div>
          <h4>符号与维度</h4>
          <table>
            <tbody>
              {item.symbols.map((s: any, i: number) => (
                <tr key={i}>
                  <td className="symbol">{s.symbol}</td>
                  <td>
                    {s.meaning}
                    <small>{s.shape}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <div className="row-between">
            <h4>逐步理解</h4>
            <span className="muted small">
              {item.derivation === "source" ? "原文推导" : "辅助教学解释"}
            </span>
          </div>
          <div className="step-tabs">
            {item.steps.map((_: string, i: number) => (
              <button
                key={i}
                aria-pressed={i === step}
                className={i === step ? "active" : ""}
                onClick={() => setStep(i)}
              >
                0{i + 1}
              </button>
            ))}
          </div>
          <div className="step-content">
            <span className="eyebrow">STEP 0{step + 1}</span>
            <p>{item.steps[step]}</p>
            <div className="row-between">
              <button
                className="icon"
                aria-label="上一步"
                disabled={step === 0}
                onClick={() => setStep(step - 1)}
              >
                <ChevronLeft size={17} />
              </button>
              <button
                className="icon"
                aria-label="下一步"
                disabled={step >= item.steps.length - 1}
                onClick={() => setStep(step + 1)}
              >
                <ChevronRight size={17} />
              </button>
            </div>
          </div>
        </div>
      </div>
      <div className="insight">
        <b>直觉</b>
        <p>{item.intuition}</p>
      </div>
      <p className="source">适用边界 · {item.limitation}</p>
    </article>
  );
}
export function FigureExplainer({ item }: { item: any }) {
  const [active, setActive] = useState(0);
  const [dimensions, setDimensions] = useState([1280, 300]);
  const region = item.regions[active];
  const box = region?.box;
  return (
    <article className="figure-explainer">
      <div className="section-label">
        <span>FIGURE / 图片解读</span>
        <Badge>{item.kind === "teaching" ? "辅助教学图" : "来源原图"}</Badge>
      </div>
      <h3>{item.title}</h3>
      {item.asset ? (
        <>
          <div className="figure-overview">
            <img
              src={fileUrl(item.asset)}
              alt={item.caption}
              onLoad={(e) =>
                setDimensions([
                  e.currentTarget.naturalWidth,
                  e.currentTarget.naturalHeight,
                ])
              }
            />
            {item.regions.map(
              (r: any, i: number) =>
                r.box && (
                  <button
                    key={i}
                    aria-label={"查看区域 " + r.label}
                    className={"region-box " + (i === active ? "active" : "")}
                    style={{
                      left: r.box[0] * 100 + "%",
                      top: r.box[1] * 100 + "%",
                      width: r.box[2] * 100 + "%",
                      height: r.box[3] * 100 + "%",
                    }}
                    onClick={() => setActive(i)}
                  >
                    <span>{i + 1}</span>
                  </button>
                ),
            )}
          </div>
          <p className="source">
            {item.caption}{" "}
            <a href={fileUrl(item.asset)} target="_blank" rel="noreferrer">
              查看整图 <ArrowUpRight size={12} />
            </a>
          </p>
        </>
      ) : (
        <p className="muted">尚无原图素材，不能声称已完成看图分析。</p>
      )}
      <div className="figure-details">
        <div className="region-list">
          {item.regions.map((r: any, i: number) => (
            <button
              key={i}
              className={active === i ? "active" : ""}
              onClick={() => setActive(i)}
            >
              <span>0{i + 1}</span>
              {r.label}
            </button>
          ))}
        </div>
        <div>
          {box && item.asset && (
            <svg
              className="crop"
              viewBox={`${box[0] * dimensions[0]} ${box[1] * dimensions[1]} ${box[2] * dimensions[0]} ${box[3] * dimensions[1]}`}
              role="img"
              aria-label={region.label + " 局部放大"}
            >
              <image
                href={fileUrl(item.asset)}
                width={dimensions[0]}
                height={dimensions[1]}
              />
            </svg>
          )}
          <h4>{region?.label}</h4>
          <p>{region?.explanation}</p>
        </div>
      </div>
      <div className="insight">
        <b>这张图说明什么</b>
        <p>{item.takeaway}</p>
      </div>
      <p className="source">来源 · {item.source}</p>
    </article>
  );
}
export function CodeExplanation({ item }: { item: any }) {
  return (
    <article className="code-explanation">
      <div className="section-label">
        <span>IMPLEMENTATION / 代码对应</span>
        <Badge>
          {item.status === "teaching"
            ? "教学伪代码"
            : item.status === "executed"
              ? "有运行证据"
              : "静态分析"}
        </Badge>
      </div>
      <h3>{item.title}</h3>
      <p className="source">{item.location}</p>
      <div className="explain-columns">
        <div>
          <div className="code-head">
            <span>Python</span>
            <CopyButton text={item.code} />
          </div>
          <pre>{item.code}</pre>
        </div>
        <div>
          <h4>公式在代码中的位置</h4>
          <ul className="clean-list">
            {item.explanation.map((s: string, i: number) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
          <p className="muted">{item.formula}</p>
        </div>
      </div>
    </article>
  );
}
export function Curve({ metrics }: { metrics: any[] }) {
  const [group, setGroup] = useState("");
  const groups = [...new Set(metrics.map((m) => m.split + "/" + m.metric))];
  const selected = groups.includes(group) ? group : groups[0];
  const rows = metrics.filter((m) => m.split + "/" + m.metric === selected);
  if (!rows.length) return <Empty title="没有可核验曲线" />;
  const seeds = [...new Set(rows.map((r) => r.seed))];
  const colors = ["#28776d", "#6479b1", "#c49a4c", "#b37b9a"];
  const minX = Math.min(...rows.map((r) => r.step));
  const maxX = Math.max(...rows.map((r) => r.step));
  const minY = Math.min(...rows.map((r) => r.value));
  const maxY = Math.max(...rows.map((r) => r.value));
  const point = (r: any) => [
    55 + ((r.step - minX) / (maxX - minX || 1)) * 585,
    205 - ((r.value - minY) / (maxY - minY || 1)) * 160,
  ];
  return (
    <div className="curve">
      <div className="row-between">
        <h4>原始日志曲线</h4>
        <select
          aria-label="曲线指标"
          value={selected}
          onChange={(e) => setGroup(e.target.value)}
        >
          {groups.map((g) => (
            <option key={g}>{g}</option>
          ))}
        </select>
      </div>
      <svg
        viewBox="0 0 680 250"
        role="img"
        aria-label={selected + " 随 step 变化，下表提供精确值"}
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i}>
            <line
              x1="55"
              x2="640"
              y1={45 + i * 40}
              y2={45 + i * 40}
              stroke="#e5e9ec"
              strokeDasharray="3 4"
            />
            <text
              x="45"
              y={49 + i * 40}
              textAnchor="end"
              fontSize="11"
              fill="#798692"
            >
              {(maxY - ((maxY - minY) * i) / 4).toFixed(3)}
            </text>
          </g>
        ))}
        {seeds.map((seed, i) => (
          <polyline
            key={seed}
            fill="none"
            stroke={colors[i % colors.length]}
            strokeWidth="2.3"
            points={rows
              .filter((r) => r.seed === seed)
              .sort((a, b) => a.step - b.step)
              .map((r) => point(r).join(","))
              .join(" ")}
          />
        ))}
        <text x="55" y="225" fontSize="11" fill="#798692">
          {minX}
        </text>
        <text x="635" y="225" fontSize="11" fill="#798692">
          {maxX}
        </text>
        <text x="335" y="245" fontSize="11" fill="#798692">
          step
        </text>
      </svg>
      <div className="legend">
        {seeds.map((seed, i) => (
          <span key={seed}>
            <i style={{ background: colors[i % colors.length] }} />
            seed {seed}
          </span>
        ))}
      </div>
    </div>
  );
}
export function RunResults({ record }: { record: RecordData }) {
  const c = record.content;
  return (
    <div className="run-results">
      <div className="row-between">
        <h3>{c.title}</h3>
        <Badge tone="amber">{labels[c.verdict] || c.verdict}</Badge>
      </div>
      {c.demo && (
        <div className="notice">合成日志示例 · 非真实训练与实验成果</div>
      )}
      <div className="protocol">
        <span className="eyebrow">EVALUATION PROTOCOL</span>
        <p>{c.protocol}</p>
      </div>
      <Curve metrics={c.metrics || []} />
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Split</th>
              <th>指标</th>
              <th>seed</th>
              <th>最后记录值</th>
              <th>日志行</th>
            </tr>
          </thead>
          <tbody>
            {(c.summaries || []).map((r: any, i: number) => (
              <tr key={i}>
                <td>
                  <Badge>{r.split}</Badge>
                </td>
                <td>{r.metric}</td>
                <td>{r.seed}</td>
                <td className="numeric">{r.value}</td>
                <td>L{r.line}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="source">{c.note}</p>
      <div className="notice">
        <b>证据与判断边界</b>
        <ul>
          {(c.problems || []).map((p: string, i: number) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      </div>
      {c.blob && (
        <a
          className="text-link"
          href={fileUrl(c.blob)}
          target="_blank"
          rel="noreferrer"
        >
          打开原始日志 <ArrowUpRight size={15} />
        </a>
      )}
      <p className="source hash">SHA256 · {c.log_hash}</p>
    </div>
  );
}
