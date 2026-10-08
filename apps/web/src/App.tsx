import { useEffect, useState, type ReactNode } from "react";
import {
  Atom,
  LayoutDashboard,
  Telescope,
  BookOpen,
  FlaskConical,
  NotebookPen,
  PanelsTopLeft,
  Settings2,
  ChevronDown,
  ChevronRight,
  Plus,
  ArrowRight,
  ArrowUpRight,
  Upload,
  Search,
  GitBranch,
  CircleCheck,
  CircleDashed,
  LockKeyhole,
  HardDrive,
  Menu,
  X,
  FileText,
  RefreshCw,
  Sparkles,
  Check,
  Download,
  ExternalLink,
  Code2,
  Clock3,
  Network,
} from "lucide-react";
import { api, session, fileUrl, date, labels, type RecordData } from "./api";
import {
  Badge,
  Empty,
  Modal,
  JsonEditor,
  FormulaExplainer,
  FigureExplainer,
  CodeExplanation,
  RunResults,
  MathFormula,
} from "./components";
import { SettingsPanel, SpecEditor } from "./SettingsPanel";
import { BatchPanel } from "./BatchPanel";
import { CodeStudyPanel } from "./CodeStudyPanel";

const navigation = [
  { id: "home", title: "研究首页", icon: LayoutDashboard },
  { id: "papers", title: "论文雷达", icon: Telescope },
  { id: "reading", title: "精读工作台", icon: BookOpen },
  { id: "experiments", title: "实验工作台", icon: FlaskConical },
  { id: "notes", title: "研究记录", icon: NotebookPen },
  { id: "reports", title: "汇报中心", icon: PanelsTopLeft },
];
type Work = (fn: () => Promise<any>, message?: string) => Promise<void>;
export default function App() {
  const [projects, setProjects] = useState<RecordData[]>([]);
  const [projectId, setProjectId] = useState("");
  const [records, setRecords] = useState<RecordData[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [page, setPage] = useState("home");
  const [modal, setModal] = useState<ReactNode>(null);
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [readId, setReadId] = useState("");
  const project = projects.find((p) => p.id === projectId);
  const loadProjects = async () => {
    const p = await api<RecordData[]>("/projects");
    setProjects(p);
    return p;
  };
  const refresh = async () => {
    if (projectId) {
      const [r, j] = await Promise.all([
        api<RecordData[]>(`/projects/${projectId}/records`),
        api<any[]>(`/projects/${projectId}/jobs`),
      ]);
      setRecords(r);
      setJobs(j);
    }
  };
  useEffect(() => {
    session()
      .then(loadProjects)
      .then((p) => {
        const saved = localStorage.getItem("research-project");
        setProjectId(p.find((x) => x.id === saved)?.id || p[0]?.id || "");
        setReady(true);
      })
      .catch((e) => {
        setToast(e.message);
        setReady(true);
      });
  }, []);
  useEffect(() => {
    if (!projectId) return;
    localStorage.setItem("research-project", projectId);
    setRecords([]);
    refresh().catch((e) => setToast(e.message));
    let timer: ReturnType<typeof setTimeout>;
    const events = new EventSource(`/api/projects/${projectId}/events`);
    events.onmessage = () => {
      clearTimeout(timer);
      timer = setTimeout(() => refresh().catch(() => {}), 200);
    };
    const fallback = setInterval(() => refresh().catch(() => {}), 10000);
    return () => {
      events.close();
      clearTimeout(timer);
      clearInterval(fallback);
    };
  }, [projectId]);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 6500);
      return () => clearTimeout(t);
    }
  }, [toast]);
  const work: Work = async (fn, message = "已保存") => {
    setBusy(true);
    try {
      await fn();
      await refresh();
      setToast(message);
    } catch (e) {
      setToast(String(e));
    } finally {
      setBusy(false);
    }
  };
  const go = (next: string) => {
    setPage(next);
    setMobile(false);
    window.scrollTo({ top: 0 });
  };
  const kind = (name: string) => records.filter((r) => r.kind === name);
  const newProject = () =>
    setModal(
      <ProjectForm
        close={() => setModal(null)}
        save={async (data) => {
          const p = await api("/projects", "POST", data);
          await loadProjects();
          setProjectId(p.id);
          setModal(null);
          go("home");
        }}
      />,
    );
  const addNote = () =>
    setModal(
      <NoteForm
        records={records}
        close={() => setModal(null)}
        save={async (data) => {
          await api(`/projects/${projectId}/notes`, "POST", data);
          await refresh();
          setModal(null);
          setToast("研究记录已保存");
        }}
      />,
    );
  const upload = (type: "pdf" | "log" | "snapshot") =>
    setModal(
      <UploadForm
        type={type}
        project={projectId}
        close={() => setModal(null)}
        done={async () => {
          await refresh();
          setModal(null);
          setToast("材料已导入，原件与版本已保存");
        }}
      />,
    );
  const openReading = (id: string) => {
    setReadId(id);
    go("reading");
  };
  const pending = jobs.filter((j) => ["queued", "running"].includes(j.status));
  return (
    <div className="app-shell">
      {mobile && (
        <button
          className="mobile-backdrop"
          aria-label="关闭导航"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={"sidebar " + (mobile ? "open" : "")}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            go("home");
          }}
        >
          <span className="brand-mark">
            <Atom size={24} strokeWidth={1.7} />
          </span>
          <div>
            <strong>研序</strong>
            <small>RESEARCH STUDIO</small>
          </div>
        </a>
        <div className="project-switch">
          <span className="project-avatar">
            <GitBranch size={17} />
          </span>
          <select
            aria-label="切换研究项目"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            <option value="" disabled>
              选择研究项目
            </option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.content.title}
              </option>
            ))}
          </select>
          <ChevronDown size={13} />
        </div>
        <div className="nav-label">工作空间</div>
        <nav>
          {navigation.map((n) => (
            <button
              key={n.id}
              className={page === n.id ? "selected" : ""}
              onClick={() => go(n.id)}
            >
              <n.icon size={18} strokeWidth={1.7} />
              <span>{n.title}</span>
              {n.id === "reading" && kind("reading").length > 0 && (
                <small>{kind("reading").length}</small>
              )}
            </button>
          ))}
        </nav>
        <button className="new-project" onClick={newProject}>
          <Plus size={16} />
          新建研究项目
        </button>
        <div className="sidebar-bottom">
          <div className="local-note">
            <HardDrive size={16} />
            <div>
              本地优先<small>材料与证据保留在你的设备</small>
            </div>
            <span className="status-dot" />
          </div>
          <button
            className={page === "settings" ? "selected settings" : "settings"}
            onClick={() => go("settings")}
          >
            <Settings2 size={17} />
            环境与设置
          </button>
          <div className="profile">
            <span>研</span>
            <div>
              个人研究空间<small>Research with evidence.</small>
            </div>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon mobile-menu"
              aria-label="打开导航"
              onClick={() => setMobile(true)}
            >
              <Menu size={20} />
            </button>
            <span>我的工作空间</span>
            <ChevronRight size={13} />
            <strong>
              {navigation.find((n) => n.id === page)?.title || "环境与设置"}
            </strong>
          </div>
          <div className="top-actions">
            <span className="connection">
              <span className="status-dot" />
              {pending.length
                ? `${pending.length} 项任务处理中`
                : "本地服务已连接"}
            </span>
            <button
              className="icon"
              aria-label="刷新工作台"
              onClick={() => work(refresh, "已同步当前状态")}
            >
              <RefreshCw size={16} className={busy ? "spin" : ""} />
            </button>
            <span className="user-dot">R</span>
          </div>
        </header>
        <main className="main-content">
          {!ready ? (
            <Empty title="正在打开研究空间…" />
          ) : !project ? (
            <div className="welcome">
              <span className="eyebrow">A QUIETER WAY TO DO RESEARCH</span>
              <h1>
                让每一次探索，
                <br />
                都有清晰的来路。
              </h1>
              <p>
                把论文、公式、代码和实验，连成可追溯的研究进展。
                <br />
                从你的第一个研究问题开始。
              </p>
              <div className="actions">
                <button className="primary" onClick={newProject}>
                  <Plus size={17} />
                  创建研究项目
                </button>
                <button
                  onClick={() =>
                    work(async () => {
                      const p = await api("/demo", "POST");
                      await loadProjects();
                      setProjectId(p.id);
                    }, "已创建明确标注的教学示例")
                  }
                >
                  <BookOpen size={17} />
                  体验教学示例
                </button>
              </div>
              <div className="welcome-features">
                {[
                  [BookOpen, "读懂方法", "公式、图像与代码逐步拆解"],
                  [FlaskConical, "验证假设", "审批后运行，证据独立核验"],
                  [PanelsTopLeft, "讲清进展", "科研友好的离线 HTML 汇报"],
                ].map(([Icon, title, text]: any, i) => (
                  <div key={i}>
                    <Icon size={25} strokeWidth={1.4} />
                    <h3>{title}</h3>
                    <p>{text}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <>
              {project.content.demo && (
                <div className="demo-strip">
                  <span>
                    <BookOpen size={14} />
                    你正在浏览教学示例；所有图表与日志均非真实科研结果。
                  </span>
                  <button onClick={newProject}>
                    创建真实项目 <ArrowUpRight size={13} />
                  </button>
                </div>
              )}
              {page === "home" && (
                <>
                  <PageHeader
                    eyebrow="YOUR RESEARCH, IN FOCUS"
                    title="把注意力放回研究本身"
                    description="一个问题，一条证据链，一次有依据的推进。"
                    action={
                      <button onClick={addNote} className="primary">
                        <Plus size={16} />
                        记录进展
                      </button>
                    }
                  />
                  <section className="research-focus">
                    <div className="focus-copy">
                      <div className="section-label">
                        <span>
                          <span className="status-dot" />
                          CURRENT QUESTION / 当前研究问题
                        </span>
                        <button
                          className="subtle"
                          onClick={() => go("settings")}
                        >
                          编辑档案 <ArrowUpRight size={14} />
                        </button>
                      </div>
                      <h2>
                        {project.content.question || "你正在尝试回答什么问题？"}
                      </h2>
                      <p>
                        {project.content.bottleneck ||
                          "记录当前瓶颈，让下一篇论文和下一个实验都更有针对性。"}
                      </p>
                      <div className="focus-footer">
                        <span>
                          <GitBranch size={14} />
                          {project.content.baseline || "尚未设定 baseline"}
                        </span>
                        <Badge>
                          {project.content.audience === "student"
                            ? "深入理解模式"
                            : "算法工程模式"}
                        </Badge>
                      </div>
                    </div>
                    <div className="focus-aside">
                      <span className="eyebrow">THIS WEEK</span>
                      <h3>本周的最小推进</h3>
                      <p>
                        {project.content.goals || "设定一个可验证的小目标。"}
                      </p>
                      <button
                        className="text-link"
                        onClick={() =>
                          work(
                            () => api(`/projects/${projectId}/propose`, "POST"),
                            "研究建议已加入队列；不自动执行实验",
                          )
                        }
                      >
                        生成下一步建议 <ArrowRight size={15} />
                      </button>
                    </div>
                  </section>
                  <section className="loop-panel">
                    <div className="row-between">
                      <div>
                        <h3>研究闭环</h3>
                        <p className="muted small">
                          智能体提出建议，执行权留在你手中。
                        </p>
                      </div>
                      <Badge>
                        <LockKeyhole size={12} />
                        审批后批量执行
                      </Badge>
                    </div>
                    <div className="loop-track">
                      {[
                        ["研究问题", "定义目标"],
                        ["寻找证据", "论文与原文"],
                        ["理解方法", "公式 · 图 · 代码"],
                        ["验证假设", "预注册与实验"],
                        ["形成认识", "复盘与汇报"],
                      ].map(([title, sub], i) => (
                        <div key={title}>
                          <span className="loop-number">{i + 1}</span>
                          <div>
                            <strong>{title}</strong>
                            <small>{sub}</small>
                          </div>
                          {i < 4 && <ChevronRight size={15} />}
                        </div>
                      ))}
                    </div>
                  </section>
                  <div className="home-columns">
                    <section className="panel">
                      <div className="panel-heading">
                        <h3>
                          <BookOpen size={18} />
                          继续理解一个方法
                        </h3>
                        <button
                          className="text-link"
                          onClick={() => go("reading")}
                        >
                          全部精读 <ArrowRight size={14} />
                        </button>
                      </div>
                      {kind("reading").length ? (
                        kind("reading")
                          .slice(0, 2)
                          .map((r) => (
                            <button
                              className="reading-teaser"
                              key={r.id}
                              onClick={() => openReading(r.id)}
                            >
                              <div className="teaser-icon">
                                <FileText size={23} strokeWidth={1.4} />
                              </div>
                              <div>
                                <Badge>
                                  {r.content.demo ? "教学讲解" : "论文精读"}
                                </Badge>
                                <h3>{r.content.title}</h3>
                                <p>{r.content.summary}</p>
                                <div className="teaser-meta">
                                  <span>
                                    {r.content.formulas.length} 个公式
                                  </span>
                                  <span>{r.content.figures.length} 张图解</span>
                                  <span>
                                    {r.content.code.length} 处实现对应
                                  </span>
                                </div>
                              </div>
                              <ArrowUpRight size={19} />
                            </button>
                          ))
                      ) : (
                        <Empty title="从第一篇论文开始">
                          <button onClick={() => upload("pdf")}>
                            导入论文 PDF
                          </button>
                        </Empty>
                      )}
                    </section>
                    <section className="panel next-panel">
                      <div className="panel-heading">
                        <h3>值得推进的下一步</h3>
                        <span className="small muted">待确认</span>
                      </div>
                      {[
                        {
                          title: "补齐原始证据",
                          text: "导入正在读的论文与代码。",
                          action: () => go("papers"),
                          icon: Upload,
                        },
                        {
                          title: "明确实验协议",
                          text: "先固定数据、指标与预算。",
                          action: () => go("experiments"),
                          icon: FlaskConical,
                        },
                        {
                          title: "把进展整理成汇报",
                          text: "选择论文、实验或每周进展。",
                          action: () => go("reports"),
                          icon: PanelsTopLeft,
                        },
                      ].map((a, i) => (
                        <button
                          className="next-item"
                          onClick={a.action}
                          key={i}
                        >
                          <span>
                            <a.icon size={17} />
                          </span>
                          <div>
                            <strong>{a.title}</strong>
                            <small>{a.text}</small>
                          </div>
                          <ChevronRight size={15} />
                        </button>
                      ))}
                    </section>
                  </div>
                  <section className="panel">
                    <div className="panel-heading">
                      <h3>最近的研究记录</h3>
                      <button className="text-link" onClick={() => go("notes")}>
                        查看时间线 <ArrowRight size={14} />
                      </button>
                    </div>
                    {kind("note")
                      .slice(0, 3)
                      .map((n) => (
                        <div key={n.id} className="activity">
                          <span className="activity-dot" />
                          <div>
                            <strong>{n.content.title}</strong>
                            <p>{n.content.text}</p>
                          </div>
                          <time>{date(n.created)}</time>
                        </div>
                      ))}
                    {!kind("note").length && (
                      <p className="muted">
                        还没有记录。写下一个观察，比只记“跑完了”更有价值。
                      </p>
                    )}
                  </section>
                </>
              )}
              {page === "papers" && (
                <PaperPage
                  records={records}
                  project={projectId}
                  work={work}
                  upload={() => upload("pdf")}
                  openReading={openReading}
                  setModal={setModal}
                />
              )}
              {page === "reading" && (
                <ReadingPage
                  readings={kind("reading")}
                  papers={kind("paper")}
                  selected={readId}
                  setSelected={setReadId}
                  project={projectId}
                  refresh={refresh}
                  setModal={setModal}
                  upload={() => upload("snapshot")}
                  snapshots={kind("snapshot")}
                  studies={kind("code-study")}
                />
              )}
              {page === "experiments" && (
                <ExperimentPage
                  project={projectId}
                  records={records}
                  jobs={jobs}
                  work={work}
                  upload={() => upload("log")}
                  snapshot={() => upload("snapshot")}
                  setModal={setModal}
                  refresh={refresh}
                />
              )}
              {page === "notes" && (
                <>
                  <PageHeader
                    eyebrow="RESEARCH JOURNAL"
                    title="研究发生的地方"
                    description="记录观察、假设与失败，也记录为什么改变方向。"
                    action={
                      <button className="primary" onClick={addNote}>
                        <Plus size={16} />
                        新记录
                      </button>
                    }
                  />
                  <div className="journal">
                    {kind("note").map((n) => (
                      <article key={n.id} className="journal-entry">
                        <div className="journal-date">
                          {date(n.created)}
                          <span>v{n.version}</span>
                        </div>
                        <div className="panel">
                          <div className="row-between">
                            <Badge>
                              {
                                (
                                  {
                                    progress: "研究进展",
                                    blocker: "当前阻塞",
                                    hypothesis: "待验证假设",
                                    lesson: "候选经验",
                                    decision: "研究决策",
                                    question: "开放问题",
                                  } as any
                                )[n.content.category]
                              }
                            </Badge>
                            <span className="source">
                              {n.visibility === "final"
                                ? "最终测试范围 · 不进入规划"
                                : n.content.reviewed
                                  ? "已人工核对"
                                  : "用户记录 / 待核对"}
                            </span>
                          </div>
                          <h3>{n.content.title}</h3>
                          <p className="preserve">{n.content.text}</p>
                          {n.stale && (
                            <Badge tone="amber">引用来源已更新</Badge>
                          )}
                          <div className="actions">
                            <span className="source">
                              {n.content.refs?.length || 0} 项关联证据
                            </span>
                            {!n.content.reviewed && (
                              <button
                                className="subtle"
                                onClick={() =>
                                  work(
                                    () =>
                                      api(
                                        `/projects/${projectId}/notes/${n.id}`,
                                        "PUT",
                                        {
                                          title: n.content.title,
                                          text: n.content.text,
                                          category: n.content.category,
                                          refs: n.content.refs || [],
                                          reviewed: true,
                                          visibility: n.visibility,
                                        },
                                      ),
                                    "已记录人工核对；旧版本保留",
                                  )
                                }
                              >
                                <CircleCheck size={14} />
                                确认记录
                              </button>
                            )}
                          </div>
                        </div>
                      </article>
                    ))}
                    {!kind("note").length && (
                      <Empty title="还没有研究记录">
                        <button onClick={addNote}>记录第一个问题</button>
                      </Empty>
                    )}
                  </div>
                </>
              )}
              {page === "reports" && (
                <ReportPage
                  project={project}
                  records={records}
                  jobs={jobs}
                  work={work}
                  reloadProjects={loadProjects}
                />
              )}
              {page === "settings" && (
                <SettingsPanel
                  project={project}
                  records={records}
                  work={work}
                  refresh={refresh}
                  reloadProjects={loadProjects}
                  setModal={setModal}
                />
              )}
            </>
          )}
          <footer className="workspace-footer">
            <span>
              <Network size={13} />
              研序 · 让结论有据可循
            </span>
            <span>资料留本地 · 外发需授权 · 实验先审批</span>
          </footer>
        </main>
      </div>
      {toast && (
        <div
          role="status"
          className={"toast " + (toast.includes("Error") ? "toast-error" : "")}
        >
          <span>{toast}</span>
          <button
            className="icon"
            aria-label="关闭通知"
            onClick={() => setToast("")}
          >
            <X size={15} />
          </button>
        </div>
      )}
      {modal}
    </div>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
function ProjectForm({
  close,
  save,
}: {
  close: () => void;
  save: (data: any) => Promise<void>;
}) {
  const [error, setError] = useState("");
  return (
    <Modal title="新建研究项目" close={close}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const data = Object.fromEntries(new FormData(e.currentTarget));
          try {
            await save(data);
          } catch (e) {
            setError(String(e));
          }
        }}
      >
        <label>
          项目名称
          <input
            name="title"
            required
            placeholder="例如：低资源条件下的视觉表征学习"
          />
        </label>
        <label>
          研究问题
          <textarea
            name="question"
            placeholder="你想解释或改善什么？"
            required
          />
        </label>
        <div className="form-grid">
          <label>
            当前 baseline
            <input name="baseline" />
          </label>
          <label>
            阅读深度
            <select name="audience">
              <option value="student">深入理解 · 学生</option>
              <option value="engineer">实现优先 · 算法工程师</option>
            </select>
          </label>
        </div>
        <label>
          当前瓶颈
          <textarea name="bottleneck" />
        </label>
        <label>
          本周目标
          <input name="goals" />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="primary">创建本地研究项目</button>
        <p className="source">默认不联网检索、不上传材料、不启动实验。</p>
      </form>
    </Modal>
  );
}
function NoteForm({
  close,
  save,
  records,
}: {
  close: () => void;
  save: (data: any) => Promise<void>;
  records: RecordData[];
}) {
  const [error, setError] = useState("");
  return (
    <Modal title="记录一次研究推进" close={close}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const form = new FormData(e.currentTarget);
          const ref = records.find((r) => r.id === form.get("ref"));
          try {
            await save({
              title: form.get("title"),
              text: form.get("text"),
              category: form.get("category"),
              visibility:
                ref?.visibility === "final" ? "final" : form.get("visibility"),
              refs: ref ? [{ id: ref.id, version: ref.version }] : [],
            });
          } catch (e) {
            setError(String(e));
          }
        }}
      >
        <label>
          一句话描述
          <input name="title" required />
        </label>
        <div className="form-grid">
          <label>
            记录类型
            <select name="category">
              <option value="progress">研究进展</option>
              <option value="hypothesis">待验证假设</option>
              <option value="blocker">当前阻塞</option>
              <option value="decision">研究决策</option>
              <option value="question">开放问题</option>
              <option value="lesson">候选经验</option>
            </select>
          </label>
          <label>
            可见范围
            <select name="visibility">
              <option value="dev">开发证据 · 可用于规划</option>
              <option value="final">含最终测试 · 不用于规划</option>
            </select>
          </label>
        </div>
        <label>
          观察、依据与下一步
          <textarea
            rows={6}
            name="text"
            required
            placeholder="看到了什么？证据是什么？还有什么没有验证？"
          />
        </label>
        <label>
          关联一项证据
          <select name="ref">
            <option value="">暂不关联</option>
            {records
              .filter((r) =>
                ["paper", "reading", "run", "snapshot"].includes(r.kind),
              )
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.content.title} · v{r.version}
                </option>
              ))}
          </select>
        </label>
        {error && <p className="error">{error}</p>}
        <button className="primary">保存研究记录</button>
      </form>
    </Modal>
  );
}
function UploadForm({
  type,
  project,
  close,
  done,
}: {
  type: string;
  project: string;
  close: () => void;
  done: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <Modal
      title={
        type === "pdf"
          ? "导入论文原文"
          : type === "log"
            ? "导入实验日志"
            : "保存代码快照"
      }
      close={close}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          setBusy(true);
          try {
            await api(`/projects/${project}/${type}`, "POST", data);
            await done();
          } catch (e) {
            setError(String(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="upload-zone">
          <Upload size={28} strokeWidth={1.4} />
          <p>
            {type === "pdf"
              ? "选择 PDF，保留原文与逐页图像"
              : type === "log"
                ? "选择 JSONL，指标从日志重新解析"
                : "显式选择项目所需代码；不会执行上传文件"}
          </p>
          <input
            aria-label="选择文件"
            type="file"
            name={type === "snapshot" ? "files" : "file"}
            multiple={type === "snapshot"}
            required
            accept={
              type === "pdf"
                ? ".pdf"
                : type === "log"
                  ? ".jsonl,.log,.txt"
                  : ".py,.json,.toml,.txt,.yaml,.yml,.cfg"
            }
          />
        </div>
        {type === "snapshot" && (
          <label>
            快照名称
            <input name="title" defaultValue="当前实现 · 代码快照" />
          </label>
        )}
        {type === "log" && (
          <>
            <label>
              实验协议
              <textarea
                name="protocol"
                required
                placeholder="数据划分、指标定义、运行配置与可比较条件"
              />
            </label>
            <details>
              <summary>JSONL 日志格式</summary>
              <pre>
                {
                  '{"type":"health","healthy":true}\n{"type":"metric","metric":"loss","value":0.4,"split":"val","step":1,"seed":42}'
                }
              </pre>
              <p className="source">
                上方为格式示例。test 日志自动归入最终测试区，不参与规划。
              </p>
            </details>
          </>
        )}
        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={busy}>
          {busy ? "导入与校验中…" : "导入本地材料"}
        </button>
        <p className="source">
          PDF ≤ 25 MiB / 80 页；日志 ≤ 8 MiB；代码快照不包含凭证。
        </p>
      </form>
    </Modal>
  );
}
function PaperPage({
  records,
  project,
  work,
  upload,
  openReading,
  setModal,
}: {
  records: RecordData[];
  project: string;
  work: Work;
  upload: () => void;
  openReading: (id: string) => void;
  setModal: (v: ReactNode) => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const papers = records.filter(
    (r) =>
      r.kind === "paper" && (filter === "all" || r.content.status === filter),
  );
  return (
    <>
      <PageHeader
        eyebrow="LITERATURE RADAR"
        title="找到与你的问题有关的论文"
        description="不只追踪新论文，更关注它为什么值得现在读。"
        action={
          <div className="actions">
            <button
              onClick={() =>
                work(
                  () => api(`/projects/${project}/recommend`, "POST"),
                  "将根据当前研究档案与开发证据推荐论文；摘要级判断会明确标注",
                )
              }
            >
              <Sparkles size={16} />
              按课题推荐
            </button>
            <button className="primary" onClick={upload}>
              <Upload size={16} />
              导入论文 PDF
            </button>
          </div>
        }
      />
      <form
        className="search-box"
        onSubmit={(e) => {
          e.preventDefault();
          work(
            () => api(`/projects/${project}/search`, "POST", { query }),
            "检索已加入队列",
          );
        }}
      >
        <Search size={20} />
        <input
          aria-label="论文检索词"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="描述方法、任务或当前瓶颈，例如 attention calibration"
        />
        <button className="primary">
          检索 arXiv <ArrowRight size={15} />
        </button>
      </form>
      <div className="row-between">
        <div className="tabs">
          {[
            ["all", "全部论文"],
            ["unread", "待读"],
            ["reading", "阅读中"],
            ["read", "已读"],
            ["ignored", "已忽略"],
          ].map(([id, label]) => (
            <button
              key={id}
              className={filter === id ? "active" : ""}
              onClick={() => setFilter(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="source">只有摘要时，始终标记为摘要级推荐</span>
      </div>
      <div className="paper-list">
        {papers.map((p) => {
          const reading = records.find(
            (r) => r.kind === "reading" && r.content.paper_id === p.id,
          );
          return (
            <article key={p.id} className="panel paper-card">
              <div className="paper-icon">
                <FileText size={24} strokeWidth={1.3} />
              </div>
              <div className="paper-info">
                <div className="actions">
                  <Badge>
                    {p.content.access === "fulltext"
                      ? "已导入全文"
                      : p.content.access === "teaching"
                        ? "教学材料"
                        : "仅摘要 / 元数据"}
                  </Badge>
                  <span className="source">
                    {labels[p.content.status]} ·{" "}
                    {p.content.published?.slice(0, 10) || date(p.created)}
                  </span>
                </div>
                <h3>{p.content.title}</h3>
                <p className="abstract">{p.content.abstract}</p>
                <div className="recommendation">
                  <Sparkles size={14} />
                  <span>{p.content.reason}</span>
                </div>
                <div className="actions">
                  <button
                    onClick={() =>
                      reading
                        ? openReading(reading.id)
                        : setModal(
                            <Modal
                              title="原文与精读范围"
                              close={() => setModal(null)}
                            >
                              <p>{p.content.caution || p.content.reason}</p>
                              {p.content.blob && (
                                <a
                                  href={fileUrl(p.content.blob)}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-link"
                                >
                                  打开 PDF 原文 <ExternalLink size={14} />
                                </a>
                              )}
                              <label>
                                精读页码（每次最多 6 页，逗号分隔）
                                <input id="reading-pages" defaultValue="1" />
                              </label>
                              <button
                                className="primary"
                                onClick={() =>
                                  work(async () => {
                                    const pages = (
                                      document.getElementById(
                                        "reading-pages",
                                      ) as HTMLInputElement
                                    ).value
                                      .split(",")
                                      .map(Number);
                                    await api(
                                      `/projects/${project}/deep-read`,
                                      "POST",
                                      { paper_id: p.id, pages },
                                    );
                                    setModal(null);
                                  }, "精读已加入队列")
                                }
                              >
                                生成待核对精读
                              </button>
                              <p className="source">
                                需要已配置的模型与项目外发授权；未配置视觉能力时不会生成图解。
                              </p>
                            </Modal>,
                          )
                    }
                  >
                    <BookOpen size={15} />
                    {reading ? "继续精读" : "打开与精读"}
                  </button>
                  <select
                    aria-label={"阅读状态 " + p.content.title}
                    value={p.content.status}
                    onChange={(e) =>
                      work(() =>
                        api(`/projects/${project}/papers/${p.id}`, "PATCH", {
                          status: e.target.value,
                        }),
                      )
                    }
                  >
                    {["unread", "reading", "read", "ignored"].map((s) => (
                      <option key={s} value={s}>
                        {labels[s]}
                      </option>
                    ))}
                  </select>
                  {p.content.url && (
                    <a
                      className="subtle"
                      target="_blank"
                      rel="noreferrer"
                      href={p.content.url}
                    >
                      原始来源 <ArrowUpRight size={14} />
                    </a>
                  )}
                </div>
              </div>
            </article>
          );
        })}
        {!papers.length && (
          <Empty title="这里是你的论文候选池">
            <p>导入正在读的 PDF，或授权检索后按研究问题查找。</p>
          </Empty>
        )}
      </div>
    </>
  );
}
function ReadingPage({
  readings,
  papers,
  selected,
  setSelected,
  project,
  refresh,
  setModal,
  upload,
  snapshots,
  studies,
}: {
  readings: RecordData[];
  papers: RecordData[];
  selected: string;
  setSelected: (v: string) => void;
  project: string;
  refresh: () => Promise<void>;
  setModal: (v: ReactNode) => void;
  upload: () => void;
  snapshots: RecordData[];
  studies: RecordData[];
}) {
  const [tab, setTab] = useState("method");
  const record = readings.find((r) => r.id === selected) || readings[0];
  const c = record?.content;
  return (
    <>
      <PageHeader
        eyebrow="DEEP READING"
        title="读懂，不止读过"
        description="把一个方法拆成公式、图像和实现，让每一步都能解释。"
        action={
          <button onClick={upload}>
            <Code2 size={16} />
            导入代码快照
          </button>
        }
      />
      <div className="reading-toolbar">
        <select
          aria-label="选择精读记录"
          value={record?.id || ""}
          onChange={(e) => setSelected(e.target.value)}
        >
          <option value="" disabled>
            选择精读记录
          </option>
          {readings.map((r) => (
            <option value={r.id} key={r.id}>
              {r.content.title}
            </option>
          ))}
        </select>
        {record && (
          <button
            onClick={() =>
              setModal(
                <Modal title="校对科研讲解" close={() => setModal(null)}>
                  <JsonEditor
                    initial={c}
                    description="校对公式、原文页码、符号与图解；保存新版本，不覆盖旧解释。只有实际核对后才将 reviewed 设为 true。"
                    onSave={async (data) => {
                      await api(
                        `/projects/${project}/readings/${record.id}?version=${record.version}`,
                        "PUT",
                        data,
                      );
                      await refresh();
                      setModal(null);
                    }}
                  />
                </Modal>,
              )
            }
          >
            校对与编辑
          </button>
        )}
      </div>
      {record ? (
        <>
          <div className="reading-title">
            <div className="actions">
              <Badge>{c.demo ? "教学示例" : "论文精读"}</Badge>
              <span className="source">证据版本 v{record.version}</span>
              {record.stale && (
                <Badge tone="amber">来源已更新 · 需要复核</Badge>
              )}
            </div>
            <h2>{c.title}</h2>
            <p>{c.summary}</p>
          </div>
          <div className="tabs reading-tabs">
            {[
              ["method", "方法与公式"],
              ["figure", "图片拆解"],
              ["code", "代码对应"],
              ["source", "原文与边界"],
            ].map(([id, label]) => (
              <button
                key={id}
                className={tab === id ? "active" : ""}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="reader-paper">
            {tab === "method" && (
              <>
                <p className="reading-intro">{c.motivation}</p>
                {c.formulas.map((f: any, i: number) => (
                  <FormulaExplainer key={record.id + i} item={f} />
                ))}
                {!c.formulas.length && <Empty title="尚无公式解释" />}
              </>
            )}
            {tab === "figure" && (
              <>
                {c.figures.map((f: any, i: number) => (
                  <FigureExplainer key={i} item={f} />
                ))}
                {!c.figures.length && (
                  <Empty title="尚无经过视觉核对的图片解释" />
                )}
              </>
            )}
            {tab === "code" && (
              <>
                {c.code.map((b: any, i: number) => (
                  <CodeExplanation key={i} item={b} />
                ))}
                <h3>项目代码快照</h3>
                {snapshots.map((s) => (
                  <details key={s.id}>
                    <summary>
                      {s.content.title} · {Object.keys(s.content.files).length}{" "}
                      个文件 · 静态
                    </summary>
                    {Object.entries(s.content.files).map(
                      ([name, value]: any) => (
                        <div key={name}>
                          <h4>{name}</h4>
                          <pre>{value.text}</pre>
                          <p className="source">SHA256 {value.sha256}</p>
                        </div>
                      ),
                    )}
                  </details>
                ))}
                {!snapshots.length && (
                  <p className="muted">
                    导入真实代码后，可对照论文方法；上传本身不会运行代码。
                  </p>
                )}
              </>
            )}
            {tab === "source" && (
              <>
                <h3>局限与需要补充的证据</h3>
                <ul className="clean-list">
                  {c.limitations.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
                <h3>下一步</h3>
                <ul className="clean-list">
                  {c.next_steps.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
                {papers
                  .find((p) => p.id === c.paper_id)
                  ?.content.pages?.map((p: any) => (
                    <details key={p.number}>
                      <summary>原文第 {p.number} 页</summary>
                      <img
                        className="pdf-page"
                        src={fileUrl(p.image)}
                        alt={"论文第 " + p.number + " 页"}
                      />
                      <p className="preserve">{p.text}</p>
                    </details>
                  ))}
                <p className="source hash">记录 SHA256 · {record.hash}</p>
              </>
            )}
          </div>
        </>
      ) : (
        <Empty title="从一篇论文开始精读">
          <p>先在论文雷达导入 PDF；也可以在首页创建教学示例体验公式与图解。</p>
        </Empty>
      )}
      {(tab === "code" || !record) && (
        <CodeStudyPanel
          project={project}
          snapshots={snapshots}
          studies={studies}
          readingId={record?.id}
        />
      )}
    </>
  );
}
function ExperimentPage({
  project,
  records,
  jobs,
  work,
  upload,
  snapshot,
  setModal,
  refresh,
}: {
  project: string;
  records: RecordData[];
  jobs: any[];
  work: Work;
  upload: () => void;
  snapshot: () => void;
  setModal: (v: ReactNode) => void;
  refresh: () => Promise<void>;
}) {
  const [selected, setSelected] = useState("");
  const [tab, setTab] = useState("results");
  const runs = records.filter((r) => r.kind === "run");
  const run = runs.find((r) => r.id === selected) || runs[0];
  const [approvals, setApprovals] = useState<any[]>([]);
  useEffect(() => {
    api(`/projects/${project}/approvals`).then(setApprovals);
  }, [project, records]);
  return (
    <>
      <PageHeader
        eyebrow="HYPOTHESIS → EVIDENCE"
        title="让实验回答一个明确的问题"
        description="先冻结协议与预算，再运行、核验和比较。"
        action={
          <div className="actions">
            <button onClick={upload}>
              <Upload size={16} />
              导入日志
            </button>
            <button
              className="primary"
              onClick={() =>
                setModal(
                  <SpecEditor
                    records={records}
                    project={project}
                    close={() => setModal(null)}
                    done={refresh}
                  />,
                )
              }
            >
              <Plus size={16} />
              设计实验
            </button>
          </div>
        }
      />
      <div className="loop-policy">
        <LockKeyhole size={18} />
        <div>
          <strong>审批后执行 · 验证集驱动探索</strong>
          <p>最终测试单独审批，相关指标与派生结论不会进入研究规划。</p>
        </div>
        <Badge>协议级隔离</Badge>
      </div>
      <div className="tabs">
        {[
          ["results", "实验结果"],
          ["plans", "计划与审批"],
          ["batches", "探索批次"],
          ["tasks", "执行队列"],
        ].map(([id, title]) => (
          <button
            key={id}
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id)}
          >
            {title}
          </button>
        ))}
      </div>
      {tab === "results" && (
        <div className="experiment-layout">
          <aside className="experiment-list">
            {runs.map((r) => (
              <button
                className={run?.id === r.id ? "active" : ""}
                key={r.id}
                onClick={() => setSelected(r.id)}
              >
                <div>
                  <FlaskConical size={15} />
                  <Badge>{labels[r.content.status]}</Badge>
                </div>
                <h4>{r.content.title}</h4>
                <small>
                  {r.visibility === "final" ? "最终测试区" : "开发 / 验证集"} ·{" "}
                  {date(r.created)}
                </small>
              </button>
            ))}
            <button className="text-link" onClick={upload}>
              <Plus size={14} />
              导入新的运行
            </button>
          </aside>
          <section className="panel">
            {run ? (
              <RunResults record={run} />
            ) : (
              <Empty title="还没有实验运行">
                <p>先导入已有日志，或审批一个新实验。</p>
              </Empty>
            )}
          </section>
        </div>
      )}
      {tab === "batches" && (
        <BatchPanel
          project={project}
          records={records}
          approvals={approvals}
          work={work}
        />
      )}
      {tab === "plans" && (
        <div className="plan-list">
          <div className="notice">
            执行约定：训练脚本接收 --seed / --output-dir /
            --split，输出结构化健康度、验证集指标和选模记录。
            <button className="subtle" onClick={snapshot}>
              导入代码快照
            </button>
          </div>
          {records
            .filter((r) => r.kind === "spec")
            .map((r) => {
              const a = approvals.find((a) => a.spec_id === r.id);
              return (
                <article className="panel" key={r.id}>
                  <div className="row-between">
                    <h3>{r.content.title}</h3>
                    <Badge>
                      {r.content.phase === "final"
                        ? "最终评测 · 单独审批"
                        : "验证集探索"}
                    </Badge>
                  </div>
                  <p>{r.content.hypothesis}</p>
                  <div className="plan-facts">
                    <span>{r.content.seeds.length} 个 seed</span>
                    <span>{r.content.gpu_hours} GPU 小时上限</span>
                    <span>{r.content.timeout_seconds} 秒墙钟上限</span>
                    <span>
                      {r.content.metric} · {r.content.direction}
                    </span>
                  </div>
                  <details>
                    <summary>检查完整预注册规格与代码绑定</summary>
                    <pre>{JSON.stringify(r.content, null, 2)}</pre>
                    <p className="source hash">审批绑定 SHA256 · {r.hash}</p>
                  </details>
                  {a ? (
                    <div className="actions">
                      <Badge tone="green">已批准 · 规格冻结</Badge>
                      <button
                        className="primary"
                        onClick={() =>
                          work(
                            () =>
                              api(
                                `/projects/${project}/approvals/${a.id}/submit`,
                                "POST",
                              ),
                            "已提交受控执行队列；相同审批不会重复开跑",
                          )
                        }
                      >
                        执行已批准实验
                      </button>
                      <button
                        onClick={() =>
                          work(
                            () =>
                              api(
                                `/projects/${project}/approvals/${a.id}/sync`,
                                "POST",
                              ),
                            "状态同步已排队",
                          )
                        }
                      >
                        同步状态
                      </button>
                      <button
                        onClick={() =>
                          work(
                            () =>
                              api(
                                `/projects/${project}/approvals/${a.id}/cancel`,
                                "POST",
                              ),
                            "取消请求已排队，仅作用于本任务",
                          )
                        }
                      >
                        停止本任务
                      </button>
                    </div>
                  ) : (
                    <button
                      className="primary"
                      onClick={() =>
                        setModal(
                          <Modal
                            title="批准此实验及资源预算"
                            close={() => setModal(null)}
                          >
                            <p>
                              将按已冻结的代码快照、参数、数据版本和协议，在指定远程环境运行。变更需要重新审批。
                            </p>
                            <pre>
                              {JSON.stringify(
                                {
                                  title: r.content.title,
                                  snapshot: r.content.snapshot_id,
                                  remote: r.content.remote_id,
                                  seeds: r.content.seeds,
                                  gpu_hours: r.content.gpu_hours,
                                  timeout: r.content.timeout_seconds,
                                  hash: r.hash,
                                },
                                null,
                                2,
                              )}
                            </pre>
                            <div className="notice">
                              Conda/venv
                              不是恶意代码沙箱。请先核对代码与数据访问范围。
                            </div>
                            <button
                              className="primary"
                              onClick={() =>
                                work(async () => {
                                  await api(
                                    `/projects/${project}/specs/${r.id}/approve`,
                                    "POST",
                                    { hash: r.hash, acknowledge: true },
                                  );
                                  setApprovals(
                                    await api(`/projects/${project}/approvals`),
                                  );
                                  setModal(null);
                                }, "审批已记录，尚未启动训练")
                              }
                            >
                              确认批准当前规格与预算
                            </button>
                          </Modal>,
                        )
                      }
                    >
                      检查并审批
                    </button>
                  )}
                </article>
              );
            })}
          {!records.some((r) => r.kind === "spec") && (
            <Empty title="还没有待验证的实验计划" />
          )}
        </div>
      )}
      {tab === "tasks" && (
        <div className="panel">
          <h3>持久执行队列</h3>
          <p className="muted">
            断线先对账，不重新训练。实验异常与连接异常分别处理。
          </p>
          {jobs.map((j) => (
            <div className="job-row" key={j.id}>
              <Clock3 size={17} />
              <div>
                <strong>{j.kind}</strong>
                <small>
                  {date(j.created)} · {j.id}
                </small>
                {j.error && <p className="error">{j.error}</p>}
              </div>
              <Badge tone={j.status === "failed" ? "amber" : ""}>
                {labels[j.status]}
              </Badge>
            </div>
          ))}
          {!jobs.length && <Empty title="队列为空" />}
        </div>
      )}
    </>
  );
}
function ReportPage({
  project,
  records,
  jobs,
  work,
  reloadProjects,
}: {
  project: RecordData;
  records: RecordData[];
  jobs: any[];
  work: Work;
  reloadProjects: () => Promise<any>;
}) {
  const [type, setType] = useState("paper");
  const [style, setStyle] = useState(
    project.content.style === "ask" ? "" : project.content.style,
  );
  const [mode, setMode] = useState("scroll");
  const [sources, setSources] = useState<string[]>([]);
  const [final, setFinal] = useState(false);
  const [start, setStart] = useState(
    new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10),
  );
  const [end, setEnd] = useState(new Date().toISOString().slice(0, 10));
  const choices = records.filter(
    (r) => r.kind === (type === "paper" ? "reading" : "run"),
  );
  const existing = records.filter((r) => r.kind === "report");
  const example = records.find((r) => r.kind === "reading");
  return (
    <>
      <PageHeader
        eyebrow="RESEARCH, WELL EXPLAINED"
        title="讲清楚你这一周的研究"
        description="内容结构由研究决定，排版只负责让证据更清晰。"
      />
      <div className="report-types">
        {[
          {
            id: "paper",
            icon: BookOpen,
            title: "论文精读",
            text: "问题 → 方法 → 公式与图解 → 实现",
          },
          {
            id: "experiment",
            icon: FlaskConical,
            title: "实验复盘",
            text: "假设 → 协议 → 结果 → 可信度",
          },
          {
            id: "weekly",
            icon: NotebookPen,
            title: "周进展",
            text: "目标 → 新认识 → 证据 → 下一步",
          },
        ].map((t) => (
          <button
            key={t.id}
            className={type === t.id ? "active" : ""}
            onClick={() => {
              setType(t.id);
              setSources([]);
            }}
          >
            <t.icon size={22} strokeWidth={1.5} />
            <strong>{t.title}</strong>
            <p>{t.text}</p>
            <span className="radio">{type === t.id && <span />}</span>
          </button>
        ))}
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h3>
            <span className="number-label">01</span>选择科研排版
          </h3>
          <span className="source">同一段内容预览 · 选择后项目内复用</span>
        </div>
        <div className="style-choices">
          {[
            ["academic", "学术白", "清晰、克制，适合组会与方法讲解"],
            ["paper", "纸感精读", "连续阅读，适合推导与深度笔记"],
            ["lab", "实验简报", "对照优先，适合指标与实验复盘"],
          ].map(([id, title, desc]) => (
            <button
              className={"style-choice " + id + (style === id ? " chosen" : "")}
              key={id}
              onClick={() => setStyle(id)}
            >
              <div className="style-preview">
                <span>METHOD / 01</span>
                <h4>从相似度到信息聚合</h4>
                <div className="preview-equation">softmax(QKᵀ / √dₖ)V</div>
                <div className="preview-lines">
                  <i />
                  <i />
                  <i />
                </div>
                <small>① 比较　② 缩放　③ 归一化　④ 聚合</small>
              </div>
              <div className="style-caption">
                <strong>{title}</strong>
                {style === id && <CircleCheck size={17} />}
                <small>{desc}</small>
              </div>
            </button>
          ))}
        </div>
        {
          <p className="source">
            预览使用明确标注的排版示例，不是你的科研结论。
          </p>
        }
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h3>
            <span className="number-label">02</span>
            {type === "weekly" ? "设定汇报周期" : "选入证据材料"}
          </h3>
          <Badge>按版本冻结</Badge>
        </div>
        {type === "weekly" ? (
          <div className="form-grid">
            <label>
              开始日期
              <input
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              结束日期（包含当天）
              <input
                type="date"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
          </div>
        ) : (
          <div className="source-options">
            {choices.map((r) => (
              <label className="check-row" key={r.id}>
                <input
                  type="checkbox"
                  checked={sources.includes(r.id)}
                  onChange={(e) =>
                    setSources(
                      e.target.checked
                        ? [...sources, r.id]
                        : sources.filter((id) => id !== r.id),
                    )
                  }
                />
                <FileText size={17} />
                <span>
                  {r.content.title}
                  <small>
                    v{r.version} ·{" "}
                    {r.visibility === "final" ? "最终测试内容" : "开发证据"}
                    {r.stale ? " · 来源已更新" : ""}
                  </small>
                </span>
              </label>
            ))}
            {!choices.length && (
              <p className="muted">
                尚无可选材料，请先完成精读或导入实验日志。
              </p>
            )}
          </div>
        )}
        <label className="check-row">
          <input
            type="checkbox"
            checked={final}
            onChange={(e) => setFinal(e.target.checked)}
          />
          本次报告包含最终测试内容（报告不会进入研究规划）
        </label>
        <div className="export-options">
          <div>
            <label>
              展示方式
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="scroll">长页阅读 · 完整讲解</option>
                <option value="deck">翻页演示 · 章节导航</option>
              </select>
            </label>
          </div>
          <button
            className="primary"
            disabled={!style || (type !== "weekly" && sources.length === 0)}
            onClick={() =>
              work(async () => {
                await api(`/projects/${project.id}`, "PUT", {
                  ...project.content,
                  style,
                });
                await reloadProjects();
                await api(`/projects/${project.id}/reports`, "POST", {
                  kind: type,
                  title:
                    project.content.title +
                    " · " +
                    (
                      {
                        paper: "论文精读",
                        experiment: "实验复盘",
                        weekly: "每周进展",
                      } as any
                    )[type],
                  style,
                  mode,
                  sources,
                  include_final: final,
                  ...(type === "weekly"
                    ? {
                        start_day: start,
                        end_day: end,
                      }
                    : {}),
                });
              }, "科研报告已加入生成队列")
            }
          >
            <PanelsTopLeft size={17} />
            生成离线 HTML 汇报
          </button>
        </div>
        <p className="source">
          报告打包为完整目录与
          ZIP。公式无需联网，原件不会自动全部打包；新报告不覆盖旧版本。
        </p>
      </section>
      {jobs
        .filter((j) => j.kind === "report" && j.status !== "done")
        .map((j) => (
          <div
            className={"notice " + (j.status === "failed" ? "error" : "")}
            key={j.id}
          >
            {labels[j.status]} ·{" "}
            {j.error || "正在整理证据、渲染公式和校验离线资源…"}
          </div>
        ))}
      <div className="row-between">
        <h3>已生成的汇报</h3>
        <span className="source">保留生成时的证据快照</span>
      </div>
      <div className="report-list">
        {existing.map((r) => (
          <article className="panel report-card" key={r.id}>
            <span className="report-cover">
              <PanelsTopLeft size={28} strokeWidth={1.3} />
            </span>
            <div>
              <Badge>
                {
                  (
                    {
                      paper: "论文精读",
                      experiment: "实验复盘",
                      weekly: "周进展",
                    } as any
                  )[r.content.report_type]
                }
              </Badge>
              <h3>{r.content.title}</h3>
              <p className="source">
                {date(r.created)} · {r.content.style} · {r.content.mode}
                {r.stale ? " · 存在来源更新" : ""}
              </p>
            </div>
            <div className="actions">
              <a
                className="button"
                target="_blank"
                rel="noreferrer"
                href={fileUrl(r.content.entry)}
              >
                打开汇报 <ArrowUpRight size={15} />
              </a>
              <a className="button" download href={fileUrl(r.content.archive)}>
                <Download size={15} />
                下载完整包
              </a>
            </div>
          </article>
        ))}
        {!existing.length && <Empty title="你的第一份科研汇报将在这里" />}
      </div>
    </>
  );
}
