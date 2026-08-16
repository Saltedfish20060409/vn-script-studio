export type StatusToastKind = "ok" | "error" | "busy" | "info";

/** Classify studio status strings into toast kinds. */
export function classifyStatusToast(
  status: string,
  error: string
): { message: string; kind: StatusToastKind } | null {
  if (error) return { message: error, kind: "error" };
  const msg = status.trim();
  if (!msg) return null;
  if (
    /中…|中\.\.\.|进行中|保存中|生成中|提取中|检查中|合成中|归档|写入语料|入库中/.test(
      msg
    )
  ) {
    return { message: msg, kind: "busy" };
  }
  if (/已|成功|同步|下载|复制|加入|创建|重命名|回退|撤销/.test(msg)) {
    return { message: msg, kind: "ok" };
  }
  return { message: msg, kind: "info" };
}
