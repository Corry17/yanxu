import { useState } from "react";
import { api, type RecordData } from "./api";
import { CodeExplanation } from "./components";

export function CodeStudyPanel({
  project,
  snapshots,
  studies,
  readingId,
}: {
  project: string;
  snapshots: RecordData[];
  studies: RecordData[];
  readingId?: string;
}) {
  const [message, setMessage] = useState("");
  return (
    <section className="panel">
      <h3>解释当前实现</h3>
      <p className="muted small">
        仅向已授权模型发送所选文件和当前精读公式，不执行代码。
      </p>
      {snapshots.map((snapshot) => (
        <details key={snapshot.id}>
          <summary>{snapshot.content.title}</summary>
          {Object.keys(snapshot.content.files).map((filename) => (
            <div key={filename} className="row-between">
              <code>{filename}</code>
              <button
                onClick={async () => {
                  try {
                    await api(`/projects/${project}/explain-code`, "POST", {
                      snapshot_id: snapshot.id,
                      filename,
                      reading_id: readingId || null,
                    });
                    setMessage("代码讲解已排队，完成后自动显示。");
                  } catch (e) {
                    setMessage(String(e));
                  }
                }}
              >
                生成只读代码讲解
              </button>
            </div>
          ))}
        </details>
      ))}
      {message && <p className="source">{message}</p>}
      {studies.map((study) => (
        <div key={study.id}>
          <h3>{study.content.title}</h3>
          <p>{study.content.summary}</p>
          {study.stale && <p className="notice">来源已变更，请复核。</p>}
          {study.content.code.map((block: any, index: number) => (
            <CodeExplanation key={index} item={block} />
          ))}
        </div>
      ))}
    </section>
  );
}
