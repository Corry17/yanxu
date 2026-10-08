import { useEffect, useState, type ReactNode } from "react";
import {
  Cpu,
  Server,
  ShieldCheck,
  Plus,
  CalendarClock,
  Save,
  ExternalLink,
} from "lucide-react";
import { api, date, type RecordData } from "./api";
import { Badge, Modal, JsonEditor, Empty } from "./components";

type Work = (fn: () => Promise<any>, message?: string) => Promise<void>;
export function SettingsPanel({
  project,
  records,
  work,
  refresh,
  reloadProjects,
  setModal,
}: {
  project: RecordData;
  records: RecordData[];
  work: Work;
  refresh: () => Promise<void>;
  reloadProjects: () => Promise<any>;
  setModal: (v: ReactNode) => void;
}) {
  const [model, setModel] = useState<any>(null);
  const [schedules, setSchedules] = useState<any[]>([]);
  const load = async () =>
    setSchedules(await api(`/projects/${project.id}/schedules`));
  useEffect(() => {
    api("/settings/model").then(setModel);
    load();
  }, [project.id]);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">WORKSPACE SETTINGS</p>
          <h1>为研究配置合适的边界</h1>
          <p>连接只在明确授权后启用，密钥不进入研究材料。</p>
        </div>
        <Badge>
          <ShieldCheck size={13} />
          本地个人工作空间
        </Badge>
      </div>
      <section className="panel">
        <h3>研究档案</h3>
        <form
          key={project.id}
          onSubmit={(e) => {
            e.preventDefault();
            const form = new FormData(e.currentTarget);
            const values = Object.fromEntries(form);
            work(async () => {
              await api(`/projects/${project.id}`, "PUT", {
                ...project.content,
                ...values,
                search_consent: form.get("search_consent") === "on",
                model_consent: form.get("model_consent") === "on",
              });
              await reloadProjects();
            }, "研究档案已保存新版本");
          }}
        >
          <label>
            项目名称
            <input name="title" defaultValue={project.content.title} required />
          </label>
          <label>
            研究问题
            <textarea name="question" defaultValue={project.content.question} />
          </label>
          <div className="form-grid">
            <label>
              当前基线
              <input name="baseline" defaultValue={project.content.baseline} />
            </label>
            <label>
              阅读模式
              <select name="audience" defaultValue={project.content.audience}>
                <option value="student">学生 · 逐步理解</option>
                <option value="engineer">算法工程 · 实现优先</option>
              </select>
            </label>
          </div>
          <div className="form-grid">
            <label>
              当前瓶颈
              <textarea
                name="bottleneck"
                defaultValue={project.content.bottleneck}
              />
            </label>
            <label>
              本周目标
              <textarea name="goals" defaultValue={project.content.goals} />
            </label>
          </div>
          <label>
            约束条件
            <input
              name="constraints"
              defaultValue={project.content.constraints}
            />
          </label>
          <label>
            项目时区
            <input name="timezone" defaultValue={project.content.timezone} />
          </label>
          <div className="notice">
            <label className="check-row">
              <input
                type="checkbox"
                name="search_consent"
                defaultChecked={project.content.search_consent}
              />
              允许向 arXiv / Crossref 发送明确的检索词
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                name="model_consent"
                defaultChecked={project.content.model_consent}
              />
              允许将选定开发证据与论文页发送给已配置模型
            </label>
            <p className="source">
              不包含最终测试内容；论文和代码中的指令不会得到执行权限。
            </p>
          </div>
          <button className="primary">
            <Save size={16} />
            保存研究档案
          </button>
        </form>
      </section>
      <div className="settings-grid">
        <section className="panel">
          <div className="panel-heading">
            <h3>
              <Cpu size={18} />
              模型服务
            </h3>
            <Badge>{model?.consent ? "已配置授权" : "默认关闭"}</Badge>
          </div>
          <p className="muted">
            OpenAI-compatible HTTPS
            接口，支持文本与可选视觉输入。调用费用按项目累计，重启不清零。
          </p>
          <div className="config-summary">
            <span>模型</span>
            <b>{model?.model || "尚未配置"}</b>
            <span>密钥来源</span>
            <code>{model?.key_env || "RESEARCH_MODEL_KEY"}</code>
            <span>累计预算</span>
            <b>{model?.max_cost ?? "—"}（按所填单价币种）</b>
          </div>
          <button
            onClick={() =>
              setModal(
                <Modal title="配置模型与费用边界" close={() => setModal(null)}>
                  <JsonEditor
                    initial={model}
                    description="只填写密钥的环境变量名称，不粘贴密钥。填写服务实际输入/输出单价（每百万 token）与费用上限；consent=true 表示同意将已选材料发送给此服务。"
                    onSave={async (data) => {
                      setModel(await api("/settings/model", "PUT", data));
                      setModal(null);
                    }}
                  />
                </Modal>,
              )
            }
          >
            配置模型服务
          </button>
          <p className="source">
            重启后端前，在启动终端设置对应环境变量。调用失败保守保留预估费用。
          </p>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h3>
              <Server size={18} />
              远程 GPU
            </h3>
            <Badge>SSH + Python 环境</Badge>
          </div>
          <p className="muted">
            使用现有 SSH 别名和已确认主机指纹。首次检查会部署项目级
            runner，不安装训练依赖。
          </p>
          {records
            .filter((r) => r.kind === "remote")
            .map((r) => (
              <div className="remote-card" key={r.id}>
                <div className="row-between">
                  <strong>{r.content.title}</strong>
                  <Badge>{r.content.consent ? "已授权" : "未授权"}</Badge>
                </div>
                <p className="source">
                  {r.content.alias} · {r.content.isolation}
                </p>
                <button
                  onClick={() =>
                    setModal(
                      <Modal
                        title="部署并检查远程执行器"
                        close={() => setModal(null)}
                      >
                        <p>
                          此操作会向已授权工作目录写入带内容指纹的
                          runner，然后检查 Python 和系统信息。
                        </p>
                        <pre>{JSON.stringify(r.content, null, 2)}</pre>
                        <button
                          className="primary"
                          onClick={() =>
                            work(async () => {
                              const result = await api(
                                `/projects/${project.id}/remotes/${r.id}/doctor`,
                                "POST",
                                { acknowledge: true },
                              );
                              setModal(
                                <Modal
                                  title="远程预检结果"
                                  close={() => setModal(null)}
                                >
                                  <pre>{JSON.stringify(result, null, 2)}</pre>
                                </Modal>,
                              );
                            }, "远程预检已完成")
                          }
                        >
                          确认部署并检查
                        </button>
                      </Modal>,
                    )
                  }
                >
                  部署与预检
                </button>
              </div>
            ))}
          <button
            onClick={() =>
              setModal(
                <Modal title="添加远程 GPU 环境" close={() => setModal(null)}>
                  <JsonEditor
                    initial={{
                      title: "我的 GPU 服务器",
                      alias: "gpu",
                      root: "/home/user/research-runs",
                      python: "/home/user/miniconda3/envs/research/bin/python",
                      dataset_root: "/home/user/datasets",
                      consent: false,
                      isolation: "protocol",
                    }}
                    description="示例路径必须改为真实授权位置。consent=true 才能部署或执行。首版不运行 ProxyCommand，不关闭主机指纹校验；协议级隔离不是安全沙箱。"
                    onSave={async (data) => {
                      await api(
                        `/projects/${project.id}/remotes`,
                        "POST",
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
            <Plus size={16} />
            添加 SSH 环境
          </button>
        </section>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h3>
            <CalendarClock size={18} />
            定期研究任务
          </h3>
          <button
            onClick={() =>
              setModal(
                <Modal title="添加持久调度" close={() => setModal(null)}>
                  <JsonEditor
                    initial={{
                      kind: "weekly",
                      interval_seconds: 604800,
                      payload: {},
                    }}
                    description="kind 可选 weekly / search / propose。search 的 payload 需包含 query。只在本地服务运行时生成新任务；恢复后幂等补做最近一个应执行周期。"
                    onSave={async (data) => {
                      await api(
                        `/projects/${project.id}/schedules`,
                        "POST",
                        data,
                      );
                      await load();
                      setModal(null);
                    }}
                  />
                </Modal>,
              )
            }
          >
            <Plus size={15} />
            添加调度
          </button>
        </div>
        {schedules.map((s) => (
          <div className="job-row" key={s.id}>
            <CalendarClock size={18} />
            <div>
              <strong>
                {
                  {
                    weekly: "每周研究汇报",
                    search: "定期文献检索",
                    propose: "下一步研究建议",
                  }[s.kind as string]
                }
              </strong>
              <small>
                下次：{date(s.next_due)} · 每 {s.interval_seconds / 3600} 小时
              </small>
            </div>
            <button
              onClick={() =>
                work(async () => {
                  await api(
                    `/projects/${project.id}/schedules/${s.id}`,
                    "PATCH",
                    { enabled: !s.enabled },
                  );
                  await load();
                })
              }
            >
              {s.enabled ? "暂停" : "恢复"}
            </button>
          </div>
        ))}
        {!schedules.length && (
          <p className="muted">
            没有后台定时任务。你可以先手动完成一次完整工作流。
          </p>
        )}
      </section>
    </>
  );
}
export function SpecEditor({
  records,
  project,
  close,
  done,
}: {
  records: RecordData[];
  project: string;
  close: () => void;
  done: () => Promise<void>;
}) {
  const snapshot = records.find((r) => r.kind === "snapshot");
  const remote = records.find((r) => r.kind === "remote");
  const initial = {
    title: "新的对照实验",
    hypothesis: "请填写机制依据、预期方向与可证伪条件。",
    refs: [],
    snapshot_id: snapshot?.id || "",
    remote_id: remote?.id || "",
    train_entry: "train.py",
    smoke_entry: "smoke.py",
    parameters: {},
    seeds: [42, 123, 2026],
    dataset: "请填写数据版本",
    data_manifest: {
      "train.csv": "请填写实际 SHA256",
      "val.csv": "请填写实际 SHA256",
    },
    metric: "loss",
    direction: "min",
    threshold: 0.5,
    min_delta: 0,
    timeout_seconds: 3600,
    gpu_hours: 1,
    gpu_ids: [0],
    protocol: "请填写划分、评测口径、选模规则与保持不变的条件。",
    checkpoint: "checkpoint.bin",
    phase: "dev",
    final_from: null,
  };
  return (
    <Modal title="设计一个可核验的实验" close={close}>
      {!snapshot || !remote ? (
        <Empty title="先准备代码快照与远程环境">
          <p>
            在精读工作台导入代码，在环境与设置中添加远程
            GPU。此时不会启动任何训练。
          </p>
        </Empty>
      ) : (
        <JsonEditor
          initial={initial}
          description="填写真实数据与 hash，并核对预算。此表只保存草案；随后须单独审批与启动。最终评测用 phase=final、独立评估入口及 final_from 开发运行 ID，所有候选参数与种子保持冻结。"
          onSave={async (data) => {
            await api(`/projects/${project}/specs`, "POST", data);
            await done();
            close();
          }}
        />
      )}
    </Modal>
  );
}
