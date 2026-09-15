/**
 * 指令插入的位置计算：把要插入的指令放到**独立行**上，而不是粘在当前行中间。
 *
 * 为什么单独抽出来：这是纯字符串逻辑，最容易出细节错（行首/行尾/空文档/末尾无换行/
 * 用户选中了一段），放在组件里只能靠手工点按钮验证。抽成纯函数后可以单测覆盖。
 *
 * 规则：
 * - 光标在某行的**行首**（第 0 列）→ 插在这一行前面（把原行往下推）；
 * - 光标在行内或行尾 → 插在**当前行的下一行**（作者写完一句台词后点"插入立绘"，
 *   期望是新起一行写指令，而不是拼在这句台词后面）；
 * - 插入内容前后按需补换行，保证不与其他内容同行；
 * - 用户选了文本时按"光标在选区起点"处理（指令插入不该吞掉作者选中的内容）。
 */

export type InsertResult = {
  text: string;
  /** 插入后建议的光标位置（落在插入内容的末尾） */
  caret: number;
};

export function insertCommandAtLine(
  text: string,
  payload: string,
  selectionStart: number,
  selectionEnd?: number
): InsertResult {
  const source = text ?? "";
  const raw = payload ?? "";
  if (!raw) return { text: source, caret: selectionStart };

  const len = source.length;
  const selStart = Math.max(0, Math.min(selectionStart ?? len, len));
  // 有选区时只取起点：插入指令不应替换作者选中的正文
  void selectionEnd;

  const lineStart = source.lastIndexOf("\n", Math.max(0, selStart - 1)) + 1;
  const lineEndIdx = source.indexOf("\n", selStart);
  const lineEnd = lineEndIdx === -1 ? len : lineEndIdx;

  const atLineStart = selStart === lineStart;
  const insertAt = atLineStart ? lineStart : lineEnd;

  const before = source.slice(0, insertAt);
  const after = source.slice(insertAt);

  // 前面要不要补换行：不在文档开头，且前一个字符不是换行
  const needLead = before.length > 0 && !before.endsWith("\n");
  // 后面要不要补换行：后面还有内容，且不是以换行开头
  const needTail = after.length > 0 && !after.startsWith("\n");

  const head = needLead ? "\n" : "";
  const tail = needTail ? "\n" : "";
  // 保留 payload 原样：`if` 模板末尾的缩进正是给作者接着写正文用的
  const inserted = `${head}${raw}${tail}`;
  return {
    text: `${before}${inserted}${after}`,
    caret: before.length + head.length + raw.length,
  };
}
