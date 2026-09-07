/**
 * Agent 消息格式化工具（纯函数）——从组件文件中拆出以支持 fast-refresh。
 */
import type {
  HarnessLintResult,
  PipelineRunResult,
} from "../api/client";
import type { AgentAction, AgentChatMessage } from "../types/vn";

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
  append_script: "追加剧本",
  replace_script: "替换剧本",
  update_bible: "更新设定",
  update_meta: "更新元信息",
  propose_character_link: "提议关系",
  propose_timeline_event: "提议时间线",
  add_character_link: "写入关系",
  update_character_link: "更新关系",
  delete_character_link: "删除关系",
  add_timeline_event: "写入时间线",
  update_timeline_event: "更新时间线",
  delete_timeline_event: "删除时间线",
  scan_facts: "扫描事实",
};

const WELCOME_MARKER = "我会默认按一套面向轻小说 / 视觉小说的写作要点帮你看稿";

export function describeActions(actions: AgentAction[]): string {
  if (actions.length === 0) return "";
  const names = actions.map((a) => ACTION_LABEL[a.op] ?? a.op);
  return names.length <= 2 ? names.join("；") : `${names[0]} 等 ${names.length} 项`;
}

export function defaultWelcome(): AgentChatMessage[] {
  return [
    {
      role: "assistant",
      content:
        "我是这部作品的驻场责编（通用文学编辑）。我会默认按一套面向轻小说 / 视觉小说的写作要点帮你看稿——比如对白要能演得动、每场留个让人想读下去的钩子、别把设定像说明书一样倒出来。这些你不用管，用平常话说想续写、改哪段、卡在哪就行。\n\n若想换一位作家的眼光来参谋，点顶部 **⇄** 打开作家卡；需要多视角时可打开「多选」。右上角 **!** 有说明。卡壳或要一整场戏时，再说「自动写作：……」（旧叫法「跑流水线」也认）。",
    },
  ];
}

function isStaleWelcome(content: string): boolean {
  const t = (content || "").trim();
  if (!t.includes("驻场责编")) return false;
  return !t.includes(WELCOME_MARKER);
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
