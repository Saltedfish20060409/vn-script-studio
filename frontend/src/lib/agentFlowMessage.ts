/**
 * 「作者原话 + 流程标记（+ 附件行）」这条用户消息的拼装约定。
 *
 * 为什么要有它（线上排查得出的教训）：流程被意图路由接走时，以前只把系统那句标记记进对话——
 * `【写入设定页】请根据附件更新故事设定与角色卡。📎 第一章_改写稿.docx`——作者自己打的那句话就没了。
 * 后果有两个：
 *   1. 作者会觉得"我刚说的话消失了"（他说的是内容，记录里只剩一句命令）；
 *   2. 事后排查根本判断不出"他当时到底说了什么"。2026-09-29 那次误写就是靠
 *      "这条消息没人打过"才定位到是按钮触发的——如果记录里本来就有作者原话，一眼就能看出来。
 *
 * 约定：**作者原话永远在第一段**，系统标记第二段，附件行最后；空的部分不产生空行。
 * 标记里不再重复作者的话（否则同一句话在一条气泡里出现两遍）。
 */

export type FlowAttachment = { filename: string; chars?: number; text?: string };

/** 附件行：`文件名（N 字）`。缺 chars 时退回 text 长度；都没有则不写数字（不打印 undefined/NaN）。 */
export function attachmentLines(list: FlowAttachment[]): string[] {
  return list.map((a) => {
    const n = a.chars ?? a.text?.length;
    return typeof n === "number" && Number.isFinite(n)
      ? `${a.filename}（${n} 字）`
      : a.filename;
  });
}

/** 拼一条用户消息：作者原话 → 流程标记 → 📎 附件行。 */
export function flowUserMessage(
  mark: string,
  ask?: string,
  attachments?: string[]
): string {
  const parts: string[] = [];
  const asked = (ask ?? "").trim();
  if (asked) parts.push(asked);
  const marker = (mark ?? "").trim();
  if (marker) parts.push(marker);
  const att = (attachments ?? []).map((a) => (a ?? "").trim()).filter(Boolean);
  if (att.length) parts.push(`📎 ${att.join("、")}`);
  return parts.join("\n\n");
}
