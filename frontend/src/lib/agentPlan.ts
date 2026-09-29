/**
 * 「方案」文案：动手之前，把"这次要动工程的哪儿"翻成作者看得懂的一份清单。
 *
 * 背景：责编有几条流程会**真的写进工程**（附件写入设定页、自动写作落章、定稿归档、账本入库），
 * 以前点一下就跑了，作者只能从结果里倒推它动了什么。确认闸要在跑之前把范围摆出来，而"摆什么、
 * 怎么说"必须与后端真实行为对齐，所以集中在这一个纯模块里，而不是散在各个按钮旁边：
 * - 只说**已知的量**（附件名/字数、章名、轮次、开关），绝不预测结果——"会新增 5 条设定"这种话
 *   猜错了比不说更伤信任，模型会不会写出好东西更不是文案能承诺的；
 * - 明说**现在还没写**：确认之前工程一个字都不动（几条流程共用同一句，免得哪张卡片漏掉）；
 * - 候选类流程（事实扫描）必须说清它只进待审列表，不是直写——这正是作者最担心的地方；
 * - 单行压短：卡片按项目符号渲染，长句在这里就会被截断，所以在这里就断好。
 */

export type PlanPreview = {
  /** 卡片标题，如「写入设定页 · 待确认」 */
  title: string;
  /** 逐条列出"这次会动到什么" */
  lines: string[];
  /** 一句提醒（可选）：说明现在还没写、确认后才写 */
  note?: string;
};

export type PlanAttachment = { filename: string; chars?: number };

/** 确认前一字未写的统一说法：所有流程共用，别让某张卡片把这句话漏掉。 */
const NOT_YET = "确认前不会改动工程";

/** 设定页默认写入的栏（后端 `settings_ingest` 的 bible 字段即这五栏）。 */
const DEFAULT_BIBLE_SECTIONS = ["世界观", "背景", "大纲", "主题", "备忘"];

/** 事实扫描的去处：候选不是直写，而是进结构分析下的待审列表。 */
const INBOX = "「结构分析 → 待审列表」";

/** 章名兜底：卡片认不出是哪一章，作者就没法核对范围。 */
function chapterLabel(title?: string): string {
  const t = (title || "").trim();
  return t || "当前章";
}

/** 千分位。不用 Intl：不同环境输出不一致，会让文案断言变成碰运气。 */
function groupDigits(n: number): string {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** 字数片段；缺值/异常值一律不产出片段，避免打印出 undefined / NaN。 */
function charBit(chars?: number): string {
  if (typeof chars !== "number" || !Number.isFinite(chars) || chars < 0) return "";
  return `${groupDigits(Math.round(chars))} 字`;
}

/** 附件名兜底：没有名字也比卡片上出现空字符串强。 */
function attachmentName(a: PlanAttachment): string {
  const name = (a.filename || "").trim();
  return name || "未命名附件";
}

/** 附件行：`附件 设定.md（1,200 字）`；字数未知时只留名字。 */
function attachmentLine(a: PlanAttachment): string {
  const bit = charBit(a.chars);
  return bit ? `附件 ${attachmentName(a)}（${bit}）` : `附件 ${attachmentName(a)}`;
}

/** 多个附件：一个附件一行（逐条列清），空数组交给调用方自己说"没有附件"。 */
function attachmentLines(attachments: PlanAttachment[]): string[] {
  const list = Array.isArray(attachments) ? attachments : [];
  return list.map(attachmentLine);
}

/** 超长原文压成一行（作者自己的话要出现在方案里，但不能把卡片撑爆）。 */
function clip(text: string, max: number): string {
  const t = (text || "").replace(/\s+/g, " ").trim();
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

/** 修正轮次：缺省 2（后端 `PipelineRunIn.max_revise_rounds` 的默认值），异常值按缺省算。 */
function reviseRounds(n?: number): number {
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return 2;
  return Math.floor(n);
}

/**
 * 附件写入设定页：附件 → 设定页若干栏 + 角色卡。
 *
 * 这里刻意报"涉及几个角色"而不是"会新增几个角色"：数量是调用方给的靶子，
 * 新增/更新由模型在跑的时候定，文案不替它许愿。
 */
export function planForSettingsIngest(
  attachments: PlanAttachment[],
  opts?: { bibleSections?: string[]; characterCount?: number }
): PlanPreview {
  const list = Array.isArray(attachments) ? attachments : [];
  const sections = opts?.bibleSections ?? DEFAULT_BIBLE_SECTIONS;
  const count = opts?.characterCount;
  const lines: string[] = [];

  if (list.length === 0) lines.push("这次没有附件，只按你消息里点名的资料来");
  else lines.push(...attachmentLines(list));

  if (sections.length === 0) lines.push("写入设定页：本次不改");
  else lines.push(`写入设定页：${sections.join(" / ")}`);

  if (count === undefined) lines.push("角色卡：按资料整理，数量不预先承诺");
  else if (count > 0) lines.push(`角色卡：涉及 ${count} 个角色`);
  else lines.push("角色卡：本次不涉及角色（0 个）");

  return {
    title: "写入设定页 · 待确认",
    lines,
    note: `${NOT_YET}；确认后才写入设定页与角色卡。`,
  };
}

/**
 * 事实扫描：只出候选，不直写关系。
 *
 * 作者对这条流程最大的误解就是"AI 会不会自己改我的关系图"，所以方案里要把
 * "先入待审列表、逐条接受才写"说成两行，而不是塞进一句。
 */
export function planForFactsScan(
  attachments: PlanAttachment[],
  opts?: { chapterTitle?: string; full?: boolean }
): PlanPreview {
  const list = Array.isArray(attachments) ? attachments : [];
  const lines: string[] = [];

  lines.push(
    opts?.full
      ? "范围：整本扫描（旧内容重扫一遍）"
      : `范围：${chapterLabel(opts?.chapterTitle)}`
  );

  if (list.length === 0) lines.push("没有附件：只扫工程里已有的剧本、设定与角色卡");
  else {
    lines.push("附件只作本次扫描的粘贴来源");
    lines.push(...attachmentLines(list));
  }

  lines.push(`关系 / 时间线候选先放进${INBOX}`);
  lines.push("你在列表里逐条接受后，才会写进关系图与时间线");

  return {
    title: "事实扫描 · 待确认",
    lines,
    note: `${NOT_YET}；确认后只把候选放进待审列表。`,
  };
}

/**
 * 自动写作：规划 → 起草 → 检查 → 修正，检查通过才落章。
 *
 * 轮次与声线开关都是作者能设的，属于"已知的量"，照实写出来；通过与否是模型跑完才知道的事，
 * 所以正文那句只说条件，不承诺本章一定会被写入。
 */
export function planForPipeline(
  instruction: string,
  opts?: { chapterTitle?: string; maxReviseRounds?: number; voiceCheck?: boolean }
): PlanPreview {
  const ask = clip(instruction, 30);
  const rounds = reviseRounds(opts?.maxReviseRounds);
  const voice = opts?.voiceCheck ?? true;
  const lines: string[] = [];

  if (ask) lines.push(`你的要求：${ask}`);
  lines.push(`目标章节：${chapterLabel(opts?.chapterTitle)}`);
  lines.push("流程：规划 → 起草 → 检查 → 修正");
  lines.push(
    rounds === 0
      ? "修正上限：0 轮（只起草与检查，不自动改）"
      : `修正上限：最多 ${rounds} 轮`
  );
  lines.push(`声线检查：${voice ? "开" : "关"}`);
  lines.push("通过自动检查才写入本章正文；不通过就不写");

  return {
    title: "自动写作 · 待确认",
    lines,
    note: `${NOT_YET}；确认后才开始跑，只有检查通过才写入正文。`,
  };
}

/**
 * 定稿：检查通过才写正文 + 归档账本；被拦下就什么都不写。
 *
 * "失败什么都不写"是这条流程最要紧的一句：作者点定稿时怕的是半途落盘，
 * 所以它单独占一行，而不是藏在 note 里。
 */
export function planForFinalize(opts?: { chapterTitle?: string }): PlanPreview {
  const label = chapterLabel(opts?.chapterTitle);
  return {
    title: "定稿 · 待确认",
    lines: [
      `目标章节：${label}`,
      "先跑一遍自动检查（含声线检查）",
      "通过后写入本章正文",
      "并把本章事实、角色状态与章末伏笔记入账本",
      "检查未通过则什么都不写，只留一条运行历史",
    ],
    note: `${NOT_YET}；确认后检查通过才写入正文与账本。`,
  };
}

/**
 * 账本入库：只更新账本，正文不动。
 *
 * 这条流程容易被误解成"再改一遍稿子"，所以"正文不受影响"必须出现在卡片正文里，
 * 让作者不用先跑一次再后悔。
 */
export function planForLedgerDigest(opts?: { chapterTitle?: string }): PlanPreview {
  const label = chapterLabel(opts?.chapterTitle);
  return {
    title: "本章要点入库 · 待确认",
    lines: [
      `目标章节：${label}`,
      "读这一章，抽出事实、角色状态与章末伏笔",
      "写进项目账本（事实 / 状态 / 伏笔）",
      "正文不受影响：只更新账本，不改写稿子",
    ],
    note: `${NOT_YET}；确认后只更新账本，正文不受影响。`,
  };
}
