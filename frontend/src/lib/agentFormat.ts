/**
 * Agent 消息格式化工具（纯函数）——从组件文件中拆出以支持 fast-refresh。
 */
import type {
  HarnessLintResult,
  PipelineRunResult,
} from "../api/client";
import { copyFor, type GenreCopy } from "./genreCopy";
import type { AgentAction, AgentChatMessage } from "../types/vn";

/**
 * 动作 → 中文名。
 *
 * `append_script` / `replace_script` **故意不在这里**：它们指的是"往正文里写"，
 * 而正文在小说工程里叫"正文"、在 VN 工程里叫"剧本"。写在这个模块级常量里就
 * 等于把 VN 的叫法钉死在所有体裁上（常量在模块加载时求值一次，根本拿不到
 * 当前作品的体裁）。所以这两个 op 在 describeActions 里按传入的 copy 现取。
 */
const ACTION_LABEL: Record<string, string> = {
  add_character: "新增角色",
  update_character: "修改角色",
  delete_character: "删除角色",
  add_location: "新增地点",
  update_location: "修改地点",
  delete_location: "删除地点",
  add_location_link: "新增通路",
  delete_location_link: "删除通路",
  add_chapter: "新增章节",
  delete_chapter: "删除章节",
  rename_chapter: "重命名章节",
  update_bible: "更新设定",
  update_meta: "更新元信息",
  propose_character_link: "提议关系",
  propose_lore_entries: "提议设定条目",
  propose_timeline_event: "提议时间线",
  add_character_link: "写入关系",
  update_character_link: "更新关系",
  delete_character_link: "删除关系",
  add_timeline_event: "写入时间线",
  update_timeline_event: "更新时间线",
  delete_timeline_event: "删除时间线",
  scan_facts: "扫描事实",
};

/**
 * 把一批写入动作拼成一句人话。
 *
 * 第二个参数缺省 `copyFor("vn")` 是刻意的向后兼容：调用点（含测试）不传时看到的
 * 仍然是"追加剧本 / 替换剧本"，与改动前逐字一致；只有真的按体裁传了 copy 的
 * 调用点才会在小说工程里显示"追加正文 / 替换正文"。
 */
export function describeActions(
  actions: AgentAction[],
  copy: GenreCopy = copyFor("vn")
): string {
  if (actions.length === 0) return "";
  const names = actions.map((a) => {
    if (a.op === "append_script") return copy.appendScript;
    if (a.op === "replace_script") return copy.replaceScript;
    return ACTION_LABEL[a.op] ?? a.op;
  });
  return names.length <= 2 ? names.join("；") : `${names[0]} 等 ${names.length} 项`;
}

export function defaultWelcome(): AgentChatMessage[] {
  return [
    {
      role: "assistant",
      content:
        "我是这部作品的驻场责编。用平常话说想干什么就行——续写、改哪一段、卡在哪。\n\n改稿会先给你左右对照，你确认了才写进正文，之后还能撤回。想换一位作家的眼光，点顶部 ⇄。",
    },
  ];
}

function isStaleWelcome(content: string): boolean {
  const t = (content || "").trim();
  // 不是系统开场白（用户自己聊出来的历史）→ 绝不改动
  if (!t.includes("驻场责编")) return false;
  // 是开场白，但已经是当前这一版 → 不算旧
  // （不能只判断"含不含某个旧标记"：改版后新开场白也会被误判成旧，每次加载都白重写一遍）
  return t !== defaultWelcome()[0].content.trim();
}

/** Refresh baked-in welcome from older sessions; keep real chat history. */
export function normalizeMessages(msgs: AgentChatMessage[]): AgentChatMessage[] {
  const welcome = defaultWelcome();
  if (!Array.isArray(msgs) || msgs.length === 0) return welcome;
  const onlyAssistant = msgs.every((m) => m.role === "assistant");
  if (onlyAssistant) return welcome;
  const first = msgs[0];
  if (first?.role === "assistant" && isStaleWelcome(first.content)) {
    return [{ role: "assistant", content: welcome[0].content }, ...msgs.slice(1)];
  }
  return msgs;
}

export function formatLintBlock(data: HarnessLintResult): string {
  const head = `${data.pass ? "无硬错误" : "存在硬错误"} · error ${data.errorCount} / warn ${data.warnCount} / info ${data.infoCount}`;
  if (!data.issues?.length) return `${head}\n未发现明显 AI 腔 / 社交问题。`;
  const lines = data.issues
    .slice(0, 24)
    .map((iss) => `- [${iss.severity}] ${iss.code}：${iss.message}`);
  return [head, ...lines].join("\n");
}

export function formatPipelineResult(data: PipelineRunResult): string {
  const parts: string[] = ["### 自动写作结果"];
  parts.push(`顺序：${(data.stages || []).join(" → ") || "—"}`);
  if (typeof data.reviseRounds === "number" && data.reviseRounds > 0) {
    parts.push(`自改轮次：${data.reviseRounds}`);
  }
  if (data.runId) {
    parts.push(`运行记录：\`${data.runId}\``);
  }
  if (data.plan?.beatSheet) {
    parts.push(
      "#### 1. 规划（节拍表）\n```json\n" +
        JSON.stringify(data.plan.beatSheet, null, 2) +
        "\n```"
    );
  } else if (data.plan?.content) {
    parts.push(`#### 1. 规划\n\n${data.plan.content}`);
  }
  const draftText = data.finalDraft || data.draft || "";
  if (draftText) {
    parts.push(`#### 生成 / 修正稿\n\n${draftText}`);
  }
  if (data.check) {
    parts.push(
      `#### 检查\n\n${
        data.check.pass ? "无硬错误" : "存在硬错误"
      } · error ${data.check.errorCount ?? 0} / warn ${data.check.warnCount ?? 0}`
    );
    const issues = data.check.issues || [];
    if (issues.length) {
      parts.push(
        issues
          .slice(0, 16)
          .map((i) => `- [${i.severity}] ${i.code}：${i.message}`)
          .join("\n")
      );
    }
  }
  if (data.gate) {
    parts.push(
      `#### 自动检查\n\n${data.gate.pass ? "✅ 通过" : "❌ 未通过"} — ${
        data.gate.message || ""
      }`
    );
  }
  if (data.applied) {
    parts.push("\n_已把通过检查的终稿写入当前章节。_");
  } else if (data.applyError) {
    parts.push(`\n_没能写入章节：${data.applyError}_`);
  } else if (!data.gate?.pass) {
    parts.push(
      "\n_自动检查未通过，这次没有写入正文。可以改好后再说「自动写作」或「定稿」。_"
    );
  } else {
    parts.push("\n_检查已通过但没有写入章节（未指定章节或未开启自动写入）。_");
  }
  const trace = data.trace;
  if (trace?.length) {
    parts.push(
      "#### 阶段耗时\n\n" +
        trace
          .map(
            (t) =>
              `- ${t.stage || "?"} · ${t.ms ?? "?"}ms · ${t.ok === false ? "失败" : "ok"}`
          )
          .join("\n")
    );
  }
  return parts.join("\n\n");
}
