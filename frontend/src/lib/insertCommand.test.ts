import { describe, expect, it } from "vitest";
import { insertCommandAtLine } from "./insertCommand";

/**
 * 插入位置的行边界规则。
 *
 * 记者用户反馈："先写剧本再插入素材，指令会和 show… 挤在同一行"——
 * 根因就是按光标原样插入，没有做行对齐。这里把各种边界钉住。
 */
describe("insertCommandAtLine", () => {
  const SHOW = "show linxia sad";

  it("光标在行尾 → 指令另起一行", () => {
    const script = 'yuki "你来了。"';
    const out = insertCommandAtLine(script, SHOW, script.length);
    expect(out.text).toBe('yuki "你来了。"\nshow linxia sad');
    expect(out.caret).toBe(out.text.length);
  });

  it("光标在行内 → 也另起一行（不粘在原地）", () => {
    const script = 'yuki "你来了。"\n"雨还在下。"';
    // 光标落在这句台词中间
    const pos = script.indexOf("来了") + 1;
    const out = insertCommandAtLine(script, SHOW, pos);
    expect(out.text).toBe('yuki "你来了。"\nshow linxia sad\n"雨还在下。"');
  });

  it("光标在行首（第 0 列）→ 插在这一行前面", () => {
    const script = 'yuki "你来了。"\n"雨还在下。"';
    const lineStart = script.indexOf('"雨还在下。"');
    const out = insertCommandAtLine(script, SHOW, lineStart);
    expect(out.text).toBe('yuki "你来了。"\nshow linxia sad\n"雨还在下。"');
  });

  it("空文档 → 直接写入，不多出空行", () => {
    const out = insertCommandAtLine("", SHOW, 0);
    expect(out.text).toBe(SHOW);
    expect(out.caret).toBe(SHOW.length);
  });

  it("文档末尾没有换行时也能另起一行", () => {
    const out = insertCommandAtLine("yuki \"喂。\"", "wait 1.5", 10);
    expect(out.text).toBe('yuki "喂。"\nwait 1.5');
  });

  it("多行指令（if 模板）整块独立成行，光标落在缩进处", () => {
    const script = 'yuki "你来了。"';
    const tpl = "if affection >= 3:\n    \nelse:\n    ";
    const out = insertCommandAtLine(script, tpl, script.length);
    expect(out.text).toBe(`${script}\n${tpl}`);
    // 光标在 else 分支的缩进之后，可以直接写正文
    expect(out.text.slice(0, out.caret).endsWith("else:\n    ")).toBe(true);
  });

  it("有选区时只按光标起点插入，不吞掉选中的正文", () => {
    const script = 'yuki "你来了。"\n"雨还在下。"';
    const start = script.indexOf("你来了");
    const end = start + 3;
    const out = insertCommandAtLine(script, SHOW, start, end);
    expect(out.text).toContain("你来了。"); // 原正文没被替换掉
    expect(out.text).toBe('yuki "你来了。"\nshow linxia sad\n"雨还在下。"');
  });

  it("连续插入两条指令不会挤在同一行", () => {
    let text = 'yuki "你来了。"';
    const first = insertCommandAtLine(text, "play music bgm/rain.ogg", text.length);
    text = first.text;
    const second = insertCommandAtLine(text, "wait 1.5", first.caret);
    expect(second.text).toBe(
      'yuki "你来了。"\nplay music bgm/rain.ogg\nwait 1.5'
    );
  });

  it("越界的光标位置会被夹到文档范围内", () => {
    const out = insertCommandAtLine("a", SHOW, 999);
    expect(out.text).toBe("a\nshow linxia sad");
  });

  it("空 payload 不改动文本", () => {
    const out = insertCommandAtLine("abc", "", 1);
    expect(out.text).toBe("abc");
    expect(out.caret).toBe(1);
  });
});
