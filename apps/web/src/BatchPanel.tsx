import { useState } from "react";
import { Layers, Play, Pause, ShieldCheck } from "lucide-react";
import { api, type RecordData } from "./api";
import { Badge, Modal } from "./components";

type Work = (fn: () => Promise<any>, message?: string) => Promise<void>;
export function BatchPanel({
  project,
  records,
  approvals,
  work,
}: {
  project: string;
  records: RecordData[];
  approvals: any[];
  work: Work;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [confirm, setConfirm] = useState(false);
  const [hours, setHours] = useState(1);
  const [seconds, setSeconds] = useState(3600);
  const specs = records.filter(
    (r) =>
      r.kind === "spec" &&
      r.content.phase === "dev" &&
      !approvals.some((a) => a.spec_id === r.id),
  );
  const batches = records.filter((r) => r.kind === "batch");
  const chosen = specs.filter((r) => selected.includes(r.id));
  return (
    <>
      <section className="panel">
        <div className="panel-heading">
          <h3>
            <Layers size={18} />
            受控探索批次
          </h3>
          <Badge>最多 3 个候选 · 串行</Badge>
        </div>
        <p className="muted small">
          把同一数据、指标、种子与协议的候选一起审批。异常、预算耗尽或提升待复现时，远端停止后续候选；本机断线不会放宽预算。
        </p>
        {specs.map((s) => (
          <label className="check-row" key={s.id}>
            <input
              type="checkbox"
              checked={selected.includes(s.id)}
              disabled={!selected.includes(s.id) && selected.length >= 3}
              onChange={(e) =>
                setSelected(
                  e.target.checked
                    ? [...selected, s.id]
                    : selected.filter((id) => id !== s.id),
                )
              }
            />
            <span>
              {s.content.title}
              <small>
                {s.content.metric} · {s.content.seeds.length} 个 seed ·{" "}
                {s.content.gpu_hours} GPU 小时单项上限
              </small>
            </span>
          </label>
        ))}
        {!specs.length && (
          <p className="source">
            先设计尚未单独审批的开发实验。已有审批不能通过批次扩大权限。
          </p>
        )}
        <div className="form-grid">
          <label>
            整批 GPU 小时上限
            <input
              type="number"
              min="0.01"
              step="0.01"
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
            />
          </label>
          <label>
            整批累计执行秒数上限
            <input
              type="number"
              min="10"
              value={seconds}
              onChange={(e) => setSeconds(Number(e.target.value))}
            />
          </label>
        </div>
        <button disabled={!chosen.length} onClick={() => setConfirm(true)}>
          <ShieldCheck size={16} />
          核对并批准这组候选
        </button>
      </section>
      {batches.map((b) => {
        const members = records.filter(
          (r) =>
            r.kind === "run" &&
            b.content.approvals.includes(r.content.approval_id),
        );
        const ledger = [...members]
          .sort((a, z) => z.created.localeCompare(a.created))
          .find((r) => r.content.remote?.batch)?.content.remote.batch;
        return (
          <section className="panel" key={b.id}>
            <div className="row-between">
              <h3>{b.content.title}</h3>
              <Badge tone={ledger?.halted ? "amber" : ""}>
                {ledger?.halted
                  ? "批次已停机"
                  : `${members.filter((r) => r.content.status === "done").length} / ${b.content.approvals.length} 已完成`}
              </Badge>
            </div>
            <p className="source">
              审批 {b.id} · {b.content.batch.gpu_hours} GPU 小时 ·{" "}
              {b.content.batch.timeout_seconds} 秒累计预算
            </p>
            {ledger && (
              <p>
                已消耗 {Number(ledger.used_gpu_hours).toFixed(4)} GPU 小时；
                {ledger.reason || "尚未触发停机门禁。"}
              </p>
            )}
            <div className="actions">
              <button
                className="primary"
                disabled={!!ledger?.halted}
                onClick={() =>
                  work(
                    () =>
                      api(
                        `/projects/${project}/batches/${b.id}/submit`,
                        "POST",
                      ),
                    "已排队准备整批快照；只有全部准备完成才开始训练",
                  )
                }
              >
                <Play size={15} />
                启动已批准批次
              </button>
              <button
                onClick={() =>
                  work(
                    () =>
                      api(
                        `/projects/${project}/batches/${b.id}/cancel`,
                        "POST",
                      ),
                    "已请求停止整批；只取消本批次任务",
                  )
                }
              >
                <Pause size={15} />
                停止整批
              </button>
            </div>
          </section>
        );
      })}
      {confirm && (
        <Modal title="确认批次范围与累计预算" close={() => setConfirm(false)}>
          <p>
            以下候选按列出的順序推进，实际规格、代码和参数全部冻结。此操作只审批，不立即启动。
          </p>
          <ol>
            {chosen.map((s) => (
              <li key={s.id}>
                {s.content.title}
                <p className="source hash">{s.hash}</p>
              </li>
            ))}
          </ol>
          <p>
            总预算：{hours} GPU 小时 / {seconds}{" "}
            秒。不允许跳过失败候选继续烧算力。
          </p>
          <button
            className="primary"
            onClick={() =>
              work(async () => {
                await api(`/projects/${project}/batches`, "POST", {
                  spec_ids: chosen.map((s) => s.id),
                  hashes: chosen.map((s) => s.hash),
                  gpu_hours: hours,
                  timeout_seconds: seconds,
                  acknowledge: true,
                });
                setConfirm(false);
                setSelected([]);
              }, "批次审批已冻结；可从批次入口启动")
            }
          >
            确认批准规格与预算
          </button>
        </Modal>
      )}
    </>
  );
}
