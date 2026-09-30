/**
 * Natural-language intent routing for the studio Agent.
 * Buttons are optional shortcuts; normal speech should hit the same pipelines.
 */

type AgentIntentKind =
  | "chapter_revise"
  | "write_to_script"
  | "revise_pick"
  | "chapter_polish"
  | "chapter_lock_name"
  | "chapter_open_review"
  | "settings_ingest"
  | "facts_scan"
  | "critique_only"
  | "pipeline"
  | "style_lint"
  | "finalize"
  | "ledger_digest"
  | "brainstorm"
  | "list_mentors"
  | "chat";

export type AgentIntent = {
  kind: AgentIntentKind;
  /** Optional note / topic forwarded to the capability */
  note?: string;
  /** Locked character/name for chapter_lock_name */
  lockName?: string;
  /** Preferred revise mode when inferred from speech */
  mode?: "cut_lecture" | "human_warmth" | "light_touch";
};

function hasAttach(n: number): boolean {
  return n > 0;
}

/**
 * 改稿模式的**唯一开关**：作者自己把"改这一章 / 这份稿"这个动作说出来。
 *
 * 为什么收成白名单（作者反馈："我没提到改稿，Agent 却自己切进了改稿模式"）：
 * 旧版除了显式说法，还挂着三条启发式——① 正文超过 500 字且句中带"改"字；
 * ② 带附件且话里出现"改写/重写"；③「这一章 …… 修改」这类跨词搭配。
 * 于是作者只是**聊到**改稿、贴一段分析、或者问一句"这一章怎么改"，
 * 都会被判成"要动手改稿"，直接进改稿流程并生成改稿预览——而他并没有让谁动手。
 *
 * 现在的口径：动作词与对象词必须同时出现（或说出"改稿/回炉"这类不带对象也成立的指令）；
 * 否定（先别改 / 不要改）与征询（怎么改 / 要不要改）一律留在普通对话。
 */
const REVISE_ACTION =
  "帮我改|给我改|替我改|帮忙改|帮改|请改|改一下|改一版|改一遍|改改|改写(?!自|于|稿)|重写|回炉|润色|润一版|修订|修改|改稿";

/**
 * 改稿对象：哪一章 / 哪份稿 / 哪一段。
 *
 * 选区说法（这段 / 这句 / 这部分）必须在内——线上实测漏过：作者说
 * 「帮我把林夏登场这段改得更细腻」，因为列表里只有「这一段」没有「这段」，
 * 于是没被认成改稿，只回了一段点评（他想要的是改稿）。这类"选中一段再说一句"是最常见的用法，
 * 宁可多认几个说法，也不要让人再问一遍。
 */
const REVISE_TARGET =
  "这一?章|当前章|本章|这章|整章|全章|第[〇一二三四五六七八九十百零0-9]+章|正文|本文|剧本|本稿|这稿|这一稿|文稿|这一段|这段|这几段|这一?节|本场|这一场|这句|这几句|这一句|这部分|这处|这几处|这几行";

/** 动作与对象之间允许的间隔：同一句内、不隔太远（"帮我改，这一章"也算）。 */
const SENTENCE_GAP = "[^。！？!?\\n]{0,12}";

const REVISE_ASK_RE = new RegExp(
  `(?:${REVISE_ACTION})${SENTENCE_GAP}(?:${REVISE_TARGET})|(?:${REVISE_TARGET})${SENTENCE_GAP}(?:${REVISE_ACTION})`
);

/**
 * 托付口气 + 选区 + 一个"改"字。
 *
 * 为什么单列一条：最常见的用法是「帮我把林夏登场这段改得更细腻」——"帮我"与"改"隔着半句话，
 * 紧邻形式（`REVISE_ASK_RE`）对不上，于是线上它没被认成改稿，只回了一段点评。
 * 这里要求**有托付口气**（帮我/给我/麻烦…），所以「这一段改得不错」这类评价不会被算进来；
 * 「改」后面跟"写/稿/善…"的（"这部分的改写"）也排除掉，那不是命令。
 */
const ENTRUSTED_SELECTION_ASK_RE =
  /(这一段|这段|这几段|这一?节|本场|这一场|这句|这几句|这一句|这部分|这处|这几行)[^。！？!?\n]{0,6}改(?!写|稿|善|动|版|过|完|好|正|天)/;

/** 不带对象也成立的显式改稿指令（默认就是"当前这一章"）。
 *  `改稿` 后面跟"意见/建议/方向…"时是**名词**（在聊改稿这件事），不是在托付任务。 */
const REVISE_STANDALONE_RE =
  /(回炉|整章\s*(重写|改写|回炉)|全章\s*(重写|改写|回炉)|(重写|改写)\s*(一版|一遍|这一?章|当前章)|改稿(?!意见|建议|方向|方案|记录|日志|历史|清单))/;

/**
 * 写入设定页的唯一开关：**写入动作 + 设定对象同时出现**。
 *
 * 为什么（作者反馈：带着附件问"这段跟人物设定对得上吗、前后有没有矛盾"，
 * 结果被送进设定页写入流程）：旧版只要带附件、句子里出现"设定"两个字就切入库，
 * 于是"人物设定"这四个字成了开关——那是个**先写库、再回答**的流程，
 * 方向反了，而且会真的改动工程。现在只提到设定（人物设定 / 世界观 / 大纲…）
 * 一律留在普通对话，让责编先读先答；真要入库，得自己说出动作。
 */
const SETTINGS_ACTION =
  "整理|归档|录入|写入|写进|写成|存进|存入|填进|填到|更新|补充|导入|收进|放进|加进|合并|拆成|提取|抽出|沉淀";

/** 设定页里的东西。 */
const SETTINGS_NOUN =
  "设定|圣经|bible|世界观|大纲|角色卡|人设|设定条目|设定库|资料库|备忘";

const SETTINGS_INGEST_RE = new RegExp(
  `(?:${SETTINGS_ACTION})${SENTENCE_GAP}(?:${SETTINGS_NOUN})|(?:${SETTINGS_NOUN})${SENTENCE_GAP}(?:${SETTINGS_ACTION})`
);

/** 事实扫描（关系 / 时间线）的对象与动作：光提到"人物关系"不算要扫。 */
const FACTS_NOUN = "关系图|人物关系|角色关系|关系|时间线|事实|伏笔";
const FACTS_ACTION =
  "扫|扫描|扫一扫|整理|梳理|提取|抽取|更新|补全|重建|录入|归档|核对|排查|登记";

const FACTS_SCAN_RE = new RegExp(
  `(?:${FACTS_ACTION})${SENTENCE_GAP}(?:${FACTS_NOUN})|(?:${FACTS_NOUN})${SENTENCE_GAP}(?:${FACTS_ACTION})`
);

/** 第一人称 / 敬语的明确托付。有它，句里的"不要改对白"是一条范围限制，
 *  而不是"别动手"。 */
const ENTRUST_RE = /(帮我|给我|替我|帮忙|请你|请帮|麻烦)/;

/** 征询口气：怎么改 / 要怎么整理 / 能不能扫描——那是在问办法，不是让谁动手。
 *  允许中间隔几个字："人物关系要怎么整理" 也是问句。 */
const ASK_HOW_RE =
  /(怎么|如何|怎样|为什么|要不要|该不该|可不可以|能不能|有没有必要)[^。！？!?\n]{0,10}(改|修|润|重写|改写|回炉|动|整理|梳理|扫描|录入|更新|补充|提取|生成|写)/;

/** 明确不要动手：只给意见、先别改、不要写入。 */
const REVISE_NEGATED_RE =
  /(只要意见|只给意见|先别改|先不要改|不要改|别改|不用改|不需要改|不要重写|别重写|不要动|别动|不要写入|先别动)/;

/** 明确不要入库 / 不要扫描。 */
const WRITE_NEGATED_RE =
  /(只要意见|只给意见|先别写|不要写|别写|不要写入|不用写|先别入库|先别扫|不要扫|别扫|不用扫|不要动|别动|先别动)/;

/** 作者是否**明确**要求改稿——`chapter_revise` 的唯一入口。 */
function explicitReviseAsk(text: string): boolean {
  const explicit = REVISE_STANDALONE_RE.test(text) || REVISE_ASK_RE.test(text);
  const trusted = ENTRUST_RE.test(text);
  // 托付口气 + 选区 + 一个"改"字（见 ENTRUSTED_SELECTION_ASK_RE）。
  if (!explicit && !(trusted && ENTRUSTED_SELECTION_ASK_RE.test(text))) return false;
  // 说了"帮我改"同时在限制范围（"帮我改这一章，不要改对白"）仍是明确要求，
  // 所以否定/征询只在**没有**托付口气时才把整句打回普通对话。
  if (trusted) return true;
  if (REVISE_NEGATED_RE.test(text)) return false;
  if (ASK_HOW_RE.test(text)) return false;
  return true;
}

/** 作者是否**明确**要求把附件写进设定页——`settings_ingest` 的唯一入口。 */
function settingsIngestAsk(text: string): boolean {
  if (!SETTINGS_INGEST_RE.test(text)) return false;
  // 问办法（"这些设定怎么整理进库里"）与"先别写"一律不上手。
  if (ASK_HOW_RE.test(text)) return false;
  if (WRITE_NEGATED_RE.test(text)) return false;
  return true;
}

/** 作者是否**明确**要求扫关系 / 时间线——`facts_scan` 的唯一入口。
 *  该流程会真的跑一遍扫描并改工程（候选进待审列表），所以同样只认说出口的动作。 */
function factsScanAsk(text: string): boolean {
  if (!FACTS_SCAN_RE.test(text)) return false;
  if (ASK_HOW_RE.test(text)) return false;
  if (WRITE_NEGATED_RE.test(text)) return false;
  return true;
}

/** True when user explicitly wants discussion only. */
function wantsCritiqueOnly(text: string): boolean {
  if (explicitReviseAsk(text)) return false;
  return /(只要意见|先别改|先不要改|不要写入|你觉得对吗|这个分析对吗|点评一下|审稿意见|修改意见(?!.*改))/u.test(
    text
  );
}

/** 明确要求"把内容落到稿子里"。 */
const WRITE_TO_SCRIPT_RE =
  /(写入|写进|存进|存入|放进|落到|落进|落盘|录进)[^。！？!?\n]{0,6}(正文|剧本|稿子|稿件|章节|工程)|(把|将)[^。！？!?\n]{0,24}(写|存|放|落)(进|入|到|盘)[^。！？!?\n]{0,6}(正文|剧本|稿子|稿件|章节|工程)/;

/**
 * Infer capability from user text + attachment count.
 * Prefer specific studio pipelines over generic chat when intent is clear.
 */
export function inferAgentIntent(text: string, attachmentCount = 0): AgentIntent {
  const trimmed = (text || "").trim();
  const t = trimmed || (hasAttach(attachmentCount) ? "请阅读附件并协助整理" : "");

  // 自动写作 / 流水线：只认**显式指令**——"跑流水线""自动写作：…""{规划|计划}并生成…"。
  // 旧版还挂着 "请.*规划.*写" 这种松散搭配：作者把写作计划拿出来讨论
  // （"请看看我的计划怎么写"）也会被切进整场自动写作（真的烧好几轮模型）。
  if (
    /^(跑|运行)?\s*(完整)?(流水线|自动写作)/.test(t) ||
    t.startsWith("【流水线】") ||
    t.startsWith("【自动写作】") ||
    (!ASK_HOW_RE.test(t) && /(规划|计划)[^。！？!?\n]{0,8}(生成|写|续写)/.test(t))
  ) {
    const note = t
      .replace(/^【流水线】/, "")
      .replace(/^【自动写作】/, "")
      .replace(/^(跑|运行)?\s*(完整)?(流水线|自动写作)[：:\s]*/, "")
      .trim();
    return { kind: "pipeline", note: note || t };
  }

  if (/^(文风)?体检$|^风格检查/.test(t)) return { kind: "style_lint" };
  if (/^定稿(入库)?$/.test(t)) return { kind: "finalize" };
  if (/^(更新|写入|刷新)?账本$|^章节(摘要|锚点)入库$|^入库账本$/.test(t)) {
    return { kind: "ledger_digest" };
  }

  if (/^(头脑风暴|圆桌|多视角)[：:\s]/.test(t) || t === "头脑风暴") {
    return {
      kind: "brainstorm",
      note: t.replace(/^(头脑风暴|圆桌|多视角)[：:\s]*/, "").trim(),
    };
  }

  if (/^(列出|查看)?写作导师|^导师列表$|^当前导师$/.test(t)) {
    return { kind: "list_mentors" };
  }

  // 改稿后的追加指令：**必须自己说出"润"**（"再润一版""轻润一下"）。
  // 「再软一点 / 再轻一点」这类没有改稿动作的说法不再算数——话里看不出要动手，
  // 作者却会看到又生成了改稿预览，和"我没提改稿它自己切进去"是同一类问题。
  if (
    /^(再润一版|再润一次|再润一下|再润润|轻润一下|润色一下)([。！!？?\s，,、：:]|$)/.test(
      t
    )
  ) {
    return { kind: "chapter_polish", note: t, mode: "light_touch" };
  }
  if (/这段用原文|还原这段|打开对照|对照面板|挑选段落/.test(t)) {
    return { kind: "chapter_open_review", note: t };
  }
  {
    const lock = t.match(
      /别动\s*([^\s，,。！!？?]{1,12})|不要改\s*([^\s，,。！!？?]{1,12})|保留\s*([^\s，,。！!？?]{1,12})\s*的戏/
    );
    if (lock) {
      const name = (lock[1] || lock[2] || lock[3] || "").trim();
      // 改稿动作词开头的不算角色名："不要改写第三章" 里的 `写第三章` 会被 `不要改`
      // 吃掉一截，当成锁定角色是误判（它本来就该留在普通对话，或走明确改稿）。
      // 指代词开头的也不算（"别动这个想法" 是在叫停，不是锁定某个角色）——那是条
      // 会被写进偏好的指令，误判会把"这个想法"降成下一轮改稿的禁区。
      // 明确要求改稿时也不在这里提前返回："帮我改这一章，不要改对白" 是**一句改稿要求**
      // 加一条范围限制，该进改稿流程（限制留在 note 里交给模型），而不是只记偏好就结束。
      if (
        name &&
        !/结构|原文|改稿|这一章|当前章/.test(name) &&
        !/^(写|改|重|润|修|动|这个|那个|这些|那些|这|那|此|我|你|他|她|它)/.test(
          name
        ) &&
        !explicitReviseAsk(t)
      ) {
        return { kind: "chapter_lock_name", lockName: name, note: t };
      }
    }
  }

  // 显式要求"选方向"——这是打开方向选择器的**唯一入口**。
  // 以前它会在每次改章前自动弹出，逼作者在三选一里挑；但那三种方向本来就能用话说
  // （下面 mode 那几行认这些词），作者反馈"弹窗很多余"，所以改成按需打开。
  if (/^(选|挑)(个|一个)?(方向|改法|模式)|^按方向改|^选方向改|^选个方向/.test(t)) {
    return { kind: "revise_pick", note: t };
  }

  // Mode hints inside natural revise asks
  let mode: AgentIntent["mode"];
  if (/只去说明书|只要去说明书|别大改/.test(t)) mode = "cut_lecture";
  else if (/轻润|不改结构|少改/.test(t)) mode = "light_touch";
  else if (/人味|更有温度|毛边/.test(t)) mode = "human_warmth";

  // Chapter revise —— 只认作者**明确说出口**的改稿要求（见 explicitReviseAsk 的口径）。
  // 以前这里挂着"长文本带改字""带附件提到改写""这一章…修改"三条启发式，
  // 作者只是在聊稿子就被切进改稿流程；现在没说出动作就一律留在普通对话。
  if (explicitReviseAsk(t)) {
    return { kind: "chapter_revise", note: t, mode };
  }

  // 「把 X 写进正文/剧本」——明确要求**落盘**。这条走写入任务的提示词，而不是自由讨论：
  // 线上实测（2026-09-30）作者说「帮我把完整的第一章写入剧本」，走的是普通对话，
  // 模型于是把整章正文塞进 JSON 的 message 里，输出一断，JSON 全废 → 正文一个字没写进稿子。
  // 提示词里 chat 一条明写"把完整意见写进 message"，正是这个错配的源头。
  if (WRITE_TO_SCRIPT_RE.test(t)) {
    return { kind: "write_to_script", note: t };
  }

  // Settings ingest —— 真要把资料**写进**设定页：写入动作 + 设定对象同时出现（见 settingsIngestAsk）。
  // 只提到"人物设定 / 世界观 / 大纲"不算——那多半是想让责编读一遍、对照着回答。
  if (hasAttach(attachmentCount) && settingsIngestAsk(t)) {
    return { kind: "settings_ingest", note: t };
  }
  if (
    !hasAttach(attachmentCount) &&
    /(根据附件|上传的).{0,20}(设定|世界观|大纲|角色)/.test(t)
  ) {
    // No attach this turn — fall through to chat with a clear error path later
    return { kind: "chat", note: t };
  }

  // Fact / relationship / timeline scan —— 同样要求"扫描动作 + 事实对象"（见 factsScanAsk）。
  // 该流程会真跑一遍扫描并改动工程（候选进待审列表），只是聊到"人物关系"不该触发。
  if (/scan_facts/.test(t) || factsScanAsk(t)) {
    return { kind: "facts_scan", note: t };
  }

  if (
    wantsCritiqueOnly(t) ||
    (t.length > 800 && !explicitReviseAsk(t) && /对吗|意见|分析/.test(t))
  ) {
    return { kind: "critique_only", note: t };
  }

  // 附件 + 模糊的"整理一下"：**写入动作本身**要出现（不再认"根据附件"这四个字，
  // 那是"我附了份资料"的说明，不是"请写进库"的吩咐）。提到关系 / 时间线走事实扫描，
  // 提到设定对象才入库。
  if (
    hasAttach(attachmentCount) &&
    !ASK_HOW_RE.test(t) &&
    !WRITE_NEGATED_RE.test(t) &&
    /(整理进|写入|写进|录入|归档|存进|更新工程|帮我整理)/.test(t)
  ) {
    if (/(关系|时间线)/.test(t)) return { kind: "facts_scan", note: t };
    if (/(设定|角色|世界观|大纲|人设|圣经)/.test(t))
      return { kind: "settings_ingest", note: t };
  }

  return { kind: "chat" };
}
