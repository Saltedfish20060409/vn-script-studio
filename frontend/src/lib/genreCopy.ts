/**
 * 作品体裁 → 界面用词（纯函数层）。
 *
 * 为什么需要：这套工具最初的用户是视觉小说作者，界面里到处写着"剧本 / 选项 /
 * Ren'Py / 试玩"。写小说的人看到这些词的第一反应是"这不是给我用的"——哪怕他真正
 * 要的功能（正文、章节、字数、导出 Word）全都在。
 *
 * 三条设计约束：
 * 1. **判断依据是"这是哪一类作品"，不是"当前在看哪种稿"**：一本小说的 RPY 稿不该
 *    把界面切回"剧本"。所以看的是 `project.writingGenre` 与 `genre`，与 `writeMode`
 *    无关（writeMode 只决定编辑哪一份稿）。
 * 2. **显式选择优先**：`writingGenre` 有值时以它为准；没有才按 `genre` 关键词猜。
 *    猜错了作者能在设定页改一次，而不是被永久锁在某一套词里。
 * 3. **默认不变**：老工程（genre 里没有小说类关键词）一律保持原来的视觉小说用词——
 *    这是**不能用错**的方向：把 VN 作者的界面改成"正文/投稿"比反过来更糟。
 */

export type WritingGenre = "vn" | "novel";

/** genre 里出现这些词就认为是小说类作品（大小写与空格无关）。 */
const NOVEL_MARKERS = [
  "轻小说",
  "小说",
  "网文",
  "网络文学",
  "文学",
  "长篇小说",
  "短篇",
] as const;

/**
 * 这些词里**也含「小说」两个字**，但它们是视觉小说——必须先判掉。
 * （`视觉小说` 撞上 `小说` 是个真实的误判：第一版就栽在这里，测试把它钉住了。）
 */
const VN_MARKERS = [
  "视觉小说",
  "文字冒险",
  "galgame",
  "ギャルゲー",
  "乙女游戏",
  "avg",
  "adv",
] as const;

/**
 * 推断作品体裁。
 *
 * 只看 `genre` 的这几个关键词是刻意的保守策略：宁可漏判（继续用视觉小说的词），
 * 也不要把一本正在写的 VN 剧本叫成"投稿稿"。
 */
export function resolveGenre(
  project: { genre?: string | null; writingGenre?: string | null } | null | undefined
): WritingGenre {
  const explicit = (project?.writingGenre ?? "").trim().toLowerCase();
  if (explicit === "novel" || explicit === "vn") return explicit;
  const genre = (project?.genre ?? "").replace(/\s/g, "").toLowerCase();
  if (VN_MARKERS.some((marker) => genre.includes(marker))) return "vn";
  if (NOVEL_MARKERS.some((marker) => genre.includes(marker))) return "novel";
  return "vn";
}

export interface GenreCopy {
  genre: WritingGenre;
  /** 这套词怎么称呼自己（设定页的选项、说明文案里用） */
  label: string;
  /** 一部作品：剧本 / 小说 */
  work: string;
  /** 项目库：剧本库 / 作品库 */
  library: string;
  /** 新建：新建剧本 / 新建小说 */
  newWork: string;
  /** 空白作品：空白剧本 / 空白小说 */
  blankWork: string;
  /** 未命名：未命名剧本 / 未命名作品 */
  untitled: string;
  /** 写作页的正文子页签：剧本 / 正文 */
  writeTab: string;
  /** 写作格式里"文字稿"那一档：剧本 / 正文 */
  proseMode: string;
  /** 该档的说明（工具栏右侧那句） */
  proseHint: string;
  /** 另一档（给引擎的脚本）的说明：RPY / 脚本 */
  scriptMode: string;
  /** 生成脚本按钮：根据剧本生成 / 根据正文生成 */
  generateScript: string;
  /** 生成脚本按钮的悬停说明（VN 里要点明输出是 Ren'Py 脚本） */
  generateScriptHint: string;
  /** 导出当前视图：导出 .rpy / 导出 .docx */
  exportCurrent: string;
  /** 空章提示 */
  emptyChapter: string;
  /** Agent 写入动作：追加剧本 / 追加正文 */
  appendScript: string;
  /** Agent 写入动作：替换剧本 / 替换正文 */
  replaceScript: string;
}

const VN_COPY: GenreCopy = {
  genre: "vn",
  label: "视觉小说 / 游戏脚本",
  work: "剧本",
  library: "剧本库",
  newWork: "新建剧本",
  blankWork: "空白剧本",
  untitled: "未命名剧本",
  writeTab: "剧本",
  proseMode: "剧本",
  proseHint: "默认写普通剧本文字（对白写成「角色名：台词」）；想做成可试玩的游戏时，再切到 RPY 自动转换",
  scriptMode: "RPY",
  generateScript: "根据剧本生成",
  generateScriptHint: "根据自然语言剧本生成 Ren'Py 脚本",
  exportCurrent: "导出 .rpy",
  emptyChapter: "这一章还没写。旁白直接写，对白写成「角色名：台词」。",
  appendScript: "追加剧本",
  replaceScript: "替换剧本",
};

const NOVEL_COPY: GenreCopy = {
  genre: "novel",
  label: "轻小说 / 网文",
  work: "小说",
  library: "作品库",
  newWork: "新建小说",
  blankWork: "空白小说",
  untitled: "未命名作品",
  writeTab: "正文",
  proseMode: "正文",
  proseHint: "正常写正文就行：一段一段写，对白用「」或“”引起来；停笔一两秒自动保存",
  scriptMode: "脚本",
  generateScript: "生成脚本",
  generateScriptHint: "根据正文生成一份可运行的脚本（脚本是用来做成能点着玩的作品的，投稿不需要它）",
  exportCurrent: "导出 .docx",
  emptyChapter: "这一章还没写。直接开始写正文就行。",
  appendScript: "追加正文",
  replaceScript: "替换正文",
};

const TABLE: Record<WritingGenre, GenreCopy> = { vn: VN_COPY, novel: NOVEL_COPY };

export function copyFor(genre: WritingGenre): GenreCopy {
  return TABLE[genre] ?? VN_COPY;
}

/** 一步到位：给一部作品，拿它的用词表。 */
export function copyForProject(
  project: { genre?: string | null; writingGenre?: string | null } | null | undefined
): GenreCopy {
  return copyFor(resolveGenre(project));
}

/** 设定页的选择项（"自动"要写清楚它会猜成什么，否则作者不知道自己在选什么）。 */
export function genreOptions(
  project: { genre?: string | null; writingGenre?: string | null } | null | undefined
): Array<{ value: "auto" | "vn" | "novel"; label: string; hint: string }> {
  const guessed = resolveGenre({ ...project, writingGenre: "auto" });
  return [
    {
      value: "auto",
      label: "自动判断",
      hint: `按题材猜：现在是「${copyFor(guessed).label}」`,
    },
    { value: "vn", label: "视觉小说 / 游戏脚本", hint: "界面用「剧本 / 选项 / 试玩」这套词" },
    { value: "novel", label: "轻小说 / 网文", hint: "界面用「正文 / 分卷 / 投稿」这套词" },
  ];
}
