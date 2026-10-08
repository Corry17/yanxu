export type RecordData = {
  id: string;
  version: number;
  kind: string;
  project: string;
  hash: string;
  created: string;
  visibility: string;
  stale?: boolean;
  content: any;
};
let token = "";
export async function session() {
  const result = await fetch("/api/session").then((r) => r.json());
  token = result.token;
}
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const form = body instanceof FormData;
  const response = await fetch("/api" + path, {
    method,
    headers: {
      "x-research-token": token,
      ...(!form && body ? { "Content-Type": "application/json" } : {}),
    },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "服务连接失败" }));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
    );
  }
  return response.json();
}
export const fileUrl = (path: string) =>
  "/api/files/" + path.split("/").map(encodeURIComponent).join("/");
export const date = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
export const labels: Record<string, string> = {
  PASS: "达到本次判据",
  FAIL: "未达到本次判据",
  INCONCLUSIVE: "证据不足",
  UNHEALTHY: "实现异常",
  PROTOCOL_VIOLATION: "协议违规",
  queued: "等待执行",
  running: "正在执行",
  done: "已完成",
  failed: "执行失败",
  blocked: "等待人工处理",
  imported: "已导入",
  interrupted: "连接待核对",
  cancelled: "已取消",
  unread: "待读",
  reading: "阅读中",
  read: "已读",
  ignored: "已忽略",
};
