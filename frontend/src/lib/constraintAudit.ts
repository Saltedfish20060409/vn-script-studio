/**
 * 约束体检（前端即时版）。
 *
 * 与后端 `app/core/constraints.py` 同一套规则，但**用途不同**：
 * - 后端那份负责"把作者的硬规则挑出来放进提示词末尾"（必须准确，跟着生成走）；
 * - 这份负责界面上的即时提示（必须即时：作者一边写一边要看到"这两条在打架"），
 *   所以按当前编辑状态在本地算，不等保存、不发请求。
 *
 * 两边规则若将来不同步，最坏结果是提示不准（不会影响生成），可接受；
 * 与字数的处理方式一致（前端算即时数字、后端给权威统计）。
 */

export type ConstraintConflict = {
  topic: string;
  a: string;
  b: string;
  hint: string;
};

export type ConstraintAudit = {
  hard: string[];
  soft: string[];
  info: string[];
  conflicts: ConstraintConflict[];
  needsSamples: boolean;
  notes: string[];
};

const HARD_MARKERS = [
  "必须",
  "务必",
  "一定要",
  "不要",
  "不许",
  "不得",
  "禁止",
  "严禁",
  "一律",
  "绝",
  "只能",
  "唯一",
];
const SOFT_MARKERS = ["尽量", "最好", "建议", "倾向", "可以", "希望", "偏好", "适度"];

const CONFLICT_PAIRS: Array<{
  topic: string;
  a: string[];
  b: string[];
  hint: string;
}> = [
  {
    topic: "是否解释超自然",
    a: ["不要解释", "不解释", "不要说明", "别解释", "不能解释"],
    b: ["要解释清楚", "必须解释", "讲清楚设定", "把设定讲清", "要说明白"],
    hint: "克系/神秘类写法里「不解释」是恐怖来源；如果要解释，就写成体系探秘，别两头都要。",
  },
  {
    topic: "句子长短",
    a: ["短句", "简洁", "克制", "干脆"],
    b: ["长句", "绵长", "华丽", "铺陈", "抒情"],
    hint: "两种节奏可以分场合用（叙述短、氛围长），别在同一条里同时要求。",
  },
  {
    topic: "叙述人称",
    a: ["第一人称", "一人称", "我视角", "见证书"],
    b: ["第三人称", "三人称", "全知", "多视角"],
    hint: "人称必须在同一章里唯一；换人称请按章切换。",
  },
  {
    topic: "视角信息量",
    a: ["限制视角", "不知道全貌", "只写主角知道的"],
    b: ["全知", "上帝视角", "交代所有人的想法"],
    hint: "限制视角与全知互斥，同一场景只能选一个。",
  },
  {
    topic: "情绪浓度",
    a: ["不要抒情", "克制", "冷静", "客观"],
    b: ["煽情", "催泪", "浓烈", "情绪饱满"],
    hint: "要浓郁就允许抒情，要克制就去掉抒情句，别同时要求。",
  },
  {
    topic: "对白比例",
    a: ["少对白", "对白少", "以叙述为主"],
    b: ["多对白", "对白为主", "以对话推进"],
    hint: "挑一个主基调，其余当调剂。",
  },
];

export function splitConstraintLines(text: string): string[] {
  return String(text ?? "")
    .split(/[\n\r]+/)
    .map((line) => line.trim().replace(/^[-*·•\d]+[.、)．]?\s*/, "").trim())
    .filter(Boolean);
}

export function classifyConstraint(line: string): "hard" | "soft" | "info" {
  if (HARD_MARKERS.some((m) => line.includes(m))) return "hard";
  if (SOFT_MARKERS.some((m) => line.includes(m))) return "soft";
  return "info";
}

export function detectConstraintConflicts(rules: string[]): ConstraintConflict[] {
  const out: ConstraintConflict[] = [];
  for (const pair of CONFLICT_PAIRS) {
    const a = rules.filter((r) => pair.a.some((k) => r.includes(k)));
    const b = rules.filter((r) => pair.b.some((k) => r.includes(k)));
    if (a.length && b.length) {
      out.push({
        topic: pair.topic,
        a: a[0].slice(0, 80),
        b: b[0].slice(0, 80),
        hint: pair.hint,
      });
    }
  }
  return out;
}

export function auditConstraints(opts: {
  bibleText?: string;
  entryTexts?: string[];
  hasStyleSamples: boolean;
  maxRules?: number;
}): ConstraintAudit {
  const maxRules = opts.maxRules ?? 40;
  const lines = splitConstraintLines(opts.bibleText ?? "");
  for (const raw of opts.entryTexts ?? []) {
    const body = String(raw ?? "").trim();
    if (!body) continue;
    const [head, ...rest] = body.split("：");
    lines.push(rest.join("：").trim() || head.trim());
  }

  const audit: ConstraintAudit = {
    hard: [],
    soft: [],
    info: [],
    conflicts: [],
    needsSamples: false,
    notes: [],
  };
  for (const line of lines) {
    const kind = classifyConstraint(line);
    const bucket = kind === "hard" ? audit.hard : kind === "soft" ? audit.soft : audit.info;
    if (bucket.length < maxRules) bucket.push(line);
  }

  // 冲突扫全部行：世界观句子也可能和硬规则打架
  audit.conflicts = detectConstraintConflicts([...audit.hard, ...audit.soft, ...audit.info]);
  if (audit.hard.length > 0 && !opts.hasStyleSamples) {
    audit.needsSamples = true;
    audit.notes.push(
      "有硬规则但还没有文风样例：模型模仿「看得见的句子」远比遵守规则稳，建议让它学一下你的文风（2~3 段样例即可）。"
    );
  }
  if (audit.hard.length > 8) {
    audit.notes.push(
      `硬规则有 ${audit.hard.length} 条，偏多：模型一次能稳定遵守的大概是 8 条以内，建议合并同类项，其余降为「尽量」。`
    );
  }
  if (audit.conflicts.length > 0) {
    audit.notes.push(
      "检测到互相冲突的约束：冲突会让模型只写「不会违规的空话」，读起来就会很平。"
    );
  }
  return audit;
}
