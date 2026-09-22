/**
 * 关系图体检：用**确定性规则**查图上的矛盾，不花一次模型调用。
 *
 * 为什么单独做这个：一致性排查原来是"把卡片/账本/章节当文本喂给模型，让它自己比"。
 * 但图上有不少问题是**机器一眼可判**的（别人不可能既是你的父亲又是你的子女、
 * 包含关系绕成环、变量绑到一个已删角色），这类不该让模型去"感觉"，也不该花钱。
 * 所以这里先跑一遍确定性检查，模型只需要看剩下的。
 *
 * 约定：一条关系 `A --label--> B` 读作「**A 是 B 的 label**」。
 * 在这个约定下：对称标签（朋友/夫妻）出现双向 = 重复；方向性标签（父亲/师父）出现双向 = 矛盾。
 *
 * 全部规则都是保守的：只报"确定有问题"的，拿不准就不报（免得作者被噪音淹没而关掉它）。
 */

import type { VnProject } from "../types/vn";

export type RelationKind = "symmetric" | "directional";

export type RelationDef = {
  /** 规范写法：A 是 B 的 label */
  label: string;
  kind: RelationKind;
  /** 反向说法（仅用于界面建议，不参与判定） */
  inverse?: string;
  hint?: string;
};

/**
 * 角色关系词表（建议词，**不强制**）。
 *
 * 为什么要有词表：关系标签是自由文本时，"父女/父亲/爸爸"会被当成三种关系，
 * 机器就没法判断 A--父亲-->B 与 B--父亲-->A 是矛盾还是同一个意思。
 * 有了词表才谈得上确定性检查；词表外仍可自由写（只是查不了矛盾）。
 */
export const CHARACTER_RELATIONS: RelationDef[] = [
  // —— 家人（方向：长辈 → 晚辈）——
  { label: "父亲", kind: "directional", inverse: "子女" },
  { label: "母亲", kind: "directional", inverse: "子女" },
  { label: "子女", kind: "directional", inverse: "父亲" },
  { label: "兄弟姐妹", kind: "symmetric", inverse: "兄弟姐妹" },
  { label: "祖孙", kind: "directional", inverse: "祖孙" },
  { label: "养父", kind: "directional", inverse: "养子女" },
  { label: "养子女", kind: "directional", inverse: "养父" },
  { label: "监护人", kind: "directional", inverse: "被监护人" },
  { label: "被监护人", kind: "directional", inverse: "监护人" },
  // —— 师承 / 职场（方向：上位 → 下位）——
  { label: "师父", kind: "directional", inverse: "徒弟" },
  { label: "徒弟", kind: "directional", inverse: "师父" },
  { label: "上司", kind: "directional", inverse: "下属" },
  { label: "下属", kind: "directional", inverse: "上司" },
  { label: "前辈", kind: "directional", inverse: "后辈" },
  { label: "后辈", kind: "directional", inverse: "前辈" },
  { label: "雇主", kind: "directional", inverse: "雇员" },
  { label: "雇员", kind: "directional", inverse: "雇主" },
  // —— 对称关系（双向都成立，只该存一条）——
  { label: "夫妻", kind: "symmetric", hint: "只存一条即可：A 是 B 的夫妻 = B 是 A 的夫妻。" },
  { label: "恋人", kind: "symmetric" },
  { label: "前恋人", kind: "symmetric" },
  { label: "未婚夫妻", kind: "symmetric" },
  { label: "朋友", kind: "symmetric" },
  { label: "挚友", kind: "symmetric" },
  { label: "青梅竹马", kind: "symmetric" },
  { label: "同门", kind: "symmetric" },
  { label: "同学", kind: "symmetric" },
  { label: "同事", kind: "symmetric" },
  { label: "搭档", kind: "symmetric" },
  { label: "邻居", kind: "symmetric" },
  { label: "仇敌", kind: "symmetric" },
  { label: "竞争对手", kind: "symmetric" },
];

const REL_BY_LABEL = new Map(CHARACTER_RELATIONS.map((r) => [r.label, r]));

export function relationDef(label: string): RelationDef | undefined {
  return REL_BY_LABEL.get((label || "").trim());
}

export function isKnownRelation(label: string): boolean {
  return REL_BY_LABEL.has((label || "").trim());
}

/** 地点关系里表示"包含"的几种（用于成环检查） */
const CONTAINMENT_RELATIONS = new Set(["contains", "inside", "above", "below"]);

export type GraphIssue = {
  /** 稳定代号，方便测试与埋点 */
  code: string;
  severity: "error" | "warn" | "info";
  message: string;
  /** 相关实体 id（点进去用） */
  refs?: string[];
};

export type GraphAudit = {
  issues: GraphIssue[];
  counts: { error: number; warn: number; info: number };
  /** 图规模，给作者一个"我的图有多大"的直观数字 */
  size: {
    characters: number;
    relations: number;
    locations: number;
    paths: number;
    timeline: number;
    variables: number;
  };
};

const nameOf = (map: Map<string, string>, id: string) => map.get(id) || id;

/**
 * 跑一遍确定性图检查。
 *
 * @param unknownLabelLimit 未知标签最多报几条（默认 3，避免刷屏）
 */
export function auditGraph(
  project: VnProject,
  opts: { unknownLabelLimit?: number } = {}
): GraphAudit {
  const unknownLimit = opts.unknownLabelLimit ?? 3;
  const issues: GraphIssue[] = [];

  const charName = new Map((project.characters ?? []).map((c) => [c.id, c.displayName || c.id]));
  const locName = new Map((project.locations ?? []).map((l) => [l.id, l.name || l.id]));
  const chapterIds = new Set((project.chapters ?? []).map((c) => c.id));

  const links = project.characterLinks ?? [];
  const paths = project.locationLinks ?? [];
  const timeline = project.timeline ?? [];
  const variables = project.variables ?? [];

  // —— 角色关系 ——
  const seenPairs = new Set<string>();
  let unknownReported = 0;
  for (const l of links) {
    const a = nameOf(charName, l.fromId);
    const b = nameOf(charName, l.toId);
    const label = (l.label || "").trim();

    if (l.fromId === l.toId) {
      issues.push({
        code: "self_link",
        severity: "error",
        message: `${a} 有一条指向自己的关系「${label}」——自己不能是自己亲戚/师父/仇敌，删掉它。`,
        refs: [l.id],
      });
      continue;
    }
    if (!charName.has(l.fromId) || !charName.has(l.toId)) {
      issues.push({
        code: "dangling_link",
        severity: "error",
        message: `关系「${a} —${label}→ ${b}」指向了已不存在的角色，请删掉或重新选择。`,
        refs: [l.id],
      });
      continue;
    }

    const def = relationDef(label);
    if (!def && label && unknownReported < unknownLimit) {
      unknownReported += 1;
      issues.push({
        code: "unknown_relation_label",
        severity: "info",
        message: `关系「${label}」（${a} → ${b}）不在建议词表里：自由写法没问题，但机器就没法替它查矛盾。想被查的话，可换成词表里的说法。`,
        refs: [l.id],
      });
    }

    // 双向检查：对称标签双向 = 重复；方向性标签双向 = 矛盾
    const pair = `${l.fromId}|${l.toId}|${label}`;
    const reverse = `${l.toId}|${l.fromId}|${label}`;
    if (seenPairs.has(reverse)) {
      if (def?.kind === "symmetric") {
        issues.push({
          code: "duplicate_symmetric_link",
          severity: "warn",
          message: `「${a}」和「${b}」之间的「${label}」存了两条（双向各一条）。${label}是对称关系，留一条就够，另一条可以删。`,
          refs: [l.id],
        });
      } else {
        issues.push({
          code: "contradictory_direction",
          severity: "error",
          message: `「${label}」被写成了双向：${a} → ${b} 与 ${b} → ${a}。按「A 是 B 的 ${label}」的读法，这两条必有一条是错的。`,
          refs: [l.id],
        });
      }
    } else if (seenPairs.has(pair)) {
      issues.push({
        code: "duplicate_link",
        severity: "warn",
        message: `${a} → ${b} 的「${label}」重复了，删掉多余的一条。`,
        refs: [l.id],
      });
    }
    seenPairs.add(pair);
  }

  // —— 地点通路 ——
  const adj = new Map<string, Array<{ to: string; id: string; relation: string }>>();
  for (const p of paths) {
    if (p.fromId === p.toId) {
      issues.push({
        code: "self_path",
        severity: "error",
        message: `地点「${nameOf(locName, p.fromId)}」有一条指向自己的通路，删掉它。`,
        refs: [p.id],
      });
      continue;
    }
    if (!locName.has(p.fromId) || !locName.has(p.toId)) {
      issues.push({
        code: "dangling_path",
        severity: "error",
        message: `通路「${nameOf(locName, p.fromId)} → ${nameOf(locName, p.toId)}」指向了已不存在的地点，请修掉。`,
        refs: [p.id],
      });
      continue;
    }
    if (CONTAINMENT_RELATIONS.has(p.relation)) {
      const list = adj.get(p.fromId) ?? [];
      list.push({ to: p.toId, id: p.id, relation: p.relation });
      adj.set(p.fromId, list);
    }
  }
  // 包含关系成环（A 含 B 含 C 含 A）—— 纯图上就能判定
  const cycle = findCycle(adj);
  if (cycle.length > 0) {
    issues.push({
      code: "containment_cycle",
      severity: "error",
      message: `包含关系绕成了环：${cycle.map((id) => nameOf(locName, id)).join(" → ")}。地点不可能自己包含自己，请改掉其中一条。`,
      refs: cycle,
    });
  }

  // —— 时间线 ——
  const orderSeen = new Map<number, string>();
  for (const t of timeline) {
    if (t.chapterRef && !chapterIds.has(String(t.chapterRef))) {
      issues.push({
        code: "timeline_missing_chapter",
        severity: "warn",
        message: `时间线节点「${t.title || t.id}」挂在已删除的章节上，请在时间线里重新选一章（或删掉这个节点）。`,
        refs: [t.id],
      });
    }
    const ord = Number(t.order ?? 0);
    const dup = orderSeen.get(ord);
    if (dup) {
      issues.push({
        code: "timeline_order_tie",
        severity: "info",
        message: `「${dup}」和「${t.title || t.id}」的排序号相同（${ord}）：两个节点会并列，先后的先后关系就说不清了。`,
        refs: [t.id],
      });
    } else {
      orderSeen.set(ord, String(t.title || t.id));
    }
  }

  // —— 变量绑定 ——
  for (const v of variables) {
    if (v.bindCharacterId && !charName.has(v.bindCharacterId)) {
      issues.push({
        code: "variable_dangling_bind",
        severity: "error",
        message: `变量「${v.name || v.key}」绑在一个已删除的角色上，请在「剧情状态」里重新绑定或取消绑定。`,
        refs: [v.id],
      });
    }
  }

  // —— 伏笔（账本）——
  const ledger = project.writingLedger;
  for (const fo of ledger?.foreshadows ?? []) {
    if (fo.plantedChapter && !chapterIds.has(String(fo.plantedChapter))) {
      issues.push({
        code: "foreshadow_missing_chapter",
        severity: "warn",
        message: `伏笔「${(fo.hook || "").slice(0, 20)}」埋在一个已删除的章节里，账本下次更新时会尝试清理它。`,
        refs: [fo.id ?? ""],
      });
    }
  }

  const counts = { error: 0, warn: 0, info: 0 };
  for (const i of issues) counts[i.severity] += 1;

  return {
    issues,
    counts,
    size: {
      characters: charName.size,
      relations: links.length,
      locations: locName.size,
      paths: paths.length,
      timeline: timeline.length,
      variables: variables.length,
    },
  };
}

/** 在邻接表里找一条环（返回环上的节点序列，找不到返回空数组） */
function findCycle(
  adj: Map<string, Array<{ to: string; id: string; relation: string }>>
): string[] {
  const state = new Map<string, 0 | 1 | 2>();
  const stack: string[] = [];
  let found: string[] = [];

  const visit = (node: string): boolean => {
    state.set(node, 1);
    stack.push(node);
    for (const e of adj.get(node) ?? []) {
      if (state.get(e.to) === 1) {
        const from = stack.indexOf(e.to);
        found = stack.slice(from).concat(e.to);
        return true;
      }
      if (!state.get(e.to) && visit(e.to)) return true;
    }
    stack.pop();
    state.set(node, 2);
    return false;
  };

  for (const node of adj.keys()) {
    if (!state.get(node) && visit(node)) break;
  }
  return found;
}
