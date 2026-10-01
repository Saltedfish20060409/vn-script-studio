/**
 * 定点改写的**逐条勾选**：把 `patch_script` 的每条 find/replace 变成一行，
 * 作者勾选后才写。
 *
 * ## 为什么要有它
 *
 * 诊断给出的建议往往是"哪几条可以改"，而作者常常只认可其中一部分（线上那次就是：
 * 9 条建议里他明确否掉了 2 条）。以前只有"整批确认"这一个粒度，模型于是拿了整批去执行，
 * 而且执行方式是 `replace_script`——"改 7 处"变成"重写全章"。
 *
 * 现在 `patch_script` 把每条改动变成独立的 find/replace，**改动粒度就等于可勾选粒度**：
 * 卡片上逐条摆出来（改前 → 改后），勾哪几条就写哪几条，没勾的一个字都不动。
 *
 * 这个模块是纯函数，界面只负责渲染与勾选状态。
 */
import type { AgentAction } from "../types/vn";

export type PatchEditRow = {
  /** 稳定 id：`${动作下标}:${改动下标}`，勾选状态按它记 */
  id: string;
  actionIndex: number;
  editIndex: number;
  /** 这一批改哪一章（卡片上要能核对范围） */
  chapterRef: string;
  before: string;
  after: string;
};

type LooseAction = AgentAction & { [key: string]: unknown };

/** 一条 action 是不是定点改写。 */
export function isPatchAction(action: AgentAction | undefined): boolean {
  return !!action && (action as LooseAction).op === "patch_script";
}

function textField(raw: unknown): string {
  return typeof raw === "string" ? raw : "";
}

/** 这批动作里有没有定点改写（决定要不要摆勾选表）。 */
export function hasPatchEdits(actions: AgentAction[] | undefined): boolean {
  return patchEditRows(actions).length > 0;
}

/**
 * 摊平成可勾选的行。
 *
 * 后端已经做过一次归一化（别名、顶层简写），这里只认 `edits` 数组；
 * 认不出的条目**跳过**而不是编一行出来——卡片上摆出作者看不懂的行，
 * 比少摆一行更糟。
 */
export function patchEditRows(actions: AgentAction[] | undefined): PatchEditRow[] {
  const rows: PatchEditRow[] = [];
  (actions || []).forEach((action, actionIndex) => {
    if (!isPatchAction(action)) return;
    const loose = action as LooseAction;
    const chapter = textField(loose.chapterRef) || "当前章";
    const edits = Array.isArray(loose.edits) ? (loose.edits as unknown[]) : [];
    edits.forEach((raw, editIndex) => {
      if (!raw || typeof raw !== "object") return;
      const edit = raw as { find?: unknown; replace?: unknown };
      const before = textField(edit.find);
      if (!before) return;
      rows.push({
        id: `${actionIndex}:${editIndex}`,
        actionIndex,
        editIndex,
        chapterRef: chapter,
        before,
        after: textField(edit.replace),
      });
    });
  });
  return rows;
}

/**
 * 按勾选结果过滤动作：没勾的改动从 `edits` 里去掉；一条都不剩的动作整条丢掉。
 *
 * 非定点改写的动作（追加正文、改设定…）**原样保留**——勾选表只管定点改，
 * 不该顺手改变别的动作的语义。
 */
export function filterPatchActions(
  actions: AgentAction[] | undefined,
  selectedIds: Iterable<string>
): AgentAction[] {
  const selected = new Set(selectedIds);
  const out: AgentAction[] = [];
  (actions || []).forEach((action, actionIndex) => {
    if (!isPatchAction(action)) {
      out.push(action);
      return;
    }
    const loose = action as LooseAction;
    const edits = Array.isArray(loose.edits) ? (loose.edits as unknown[]) : [];
    const kept = edits.filter((_, editIndex) => selected.has(`${actionIndex}:${editIndex}`));
    if (kept.length === 0) return;
    out.push({ ...loose, edits: kept } as AgentAction);
  });
  return out;
}

/** 卡片标题上那句"这次动多少"：把改动条数与涉及章节说清。 */
export function patchPlanSummary(rows: PatchEditRow[]): string {
  if (rows.length === 0) return "";
  const chapters = Array.from(new Set(rows.map((r) => r.chapterRef)));
  const scope = chapters.length === 1 ? chapters[0] : `${chapters.length} 章`;
  return `定点改写 ${scope}：共 ${rows.length} 处`;
}
