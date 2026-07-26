/**
 * Deterministic narrative lint — catches patterns LLMs often miss when
 * reviewing their own drafts (no model call).
 */

export type LintSeverity = "error" | "warn";

export interface NarrativeLintIssue {
  severity: LintSeverity;
  code: string;
  message: string;
}

type DialogueLine = {
  speaker: string;
  text: string;
  isQuestion: boolean;
};

function parseDialogueLines(draft: string): DialogueLine[] {
  const lines = draft.replace(/\r\n/g, "\n").split("\n");
  const out: DialogueLine[] = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    // 林夏: ... | linxia "..." | 林夏：...
    const m =
      line.match(/^([^\s:：\[\]「」]{1,24})\s*[:：]\s*(.*)$/) ||
      line.match(/^([A-Za-z_][\w]*)\s+"([^"]*)"/);
    if (!m) continue;
    const speaker = m[1].trim();
    const text = (m[2] ?? "").trim();
    if (!text || /^(旁白|narration|nv)$/i.test(speaker)) continue;
    const isQuestion =
      /[?？]/.test(text) ||
      /^(难道|是不是|怎么|为什么|何处|哪|吗|么)/.test(text.replace(/^[（(][^）)]*[）)]/, ""));
    out.push({ speaker, text, isQuestion });
  }
  return out;
}

/** Rule engine: social/narrative hard fails without LLM. */
export function lintNarrativeDraft(draft: string): NarrativeLintIssue[] {
  const issues: NarrativeLintIssue[] = [];
  const t = draft.trim();
  if (!t) return issues;

  const dialogues = parseDialogueLines(t);

  // 1) Same speaker asks 2+ questions in one beat (not necessarily consecutive)
  const qCount = new Map<string, number>();
  for (const d of dialogues) {
    if (!d.isQuestion) continue;
    qCount.set(d.speaker, (qCount.get(d.speaker) ?? 0) + 1);
  }
  for (const [speaker, n] of qCount) {
    if (n >= 2) {
      issues.push({
        severity: "error",
        code: "multi_question",
        message: `「${speaker}」本拍主动追问 ${n} 次（盘问串），宜≤1 次`,
      });
    }
  }

  // 2) Q-A-Q ping-pong: A?, B answers, A? again within 6 turns
  for (let i = 0; i < dialogues.length - 2; i++) {
    const a = dialogues[i];
    if (!a.isQuestion) continue;
    for (let j = i + 1; j < Math.min(i + 6, dialogues.length); j++) {
      const mid = dialogues[j];
      if (mid.speaker === a.speaker) continue;
      for (let k = j + 1; k < Math.min(j + 5, dialogues.length); k++) {
        const again = dialogues[k];
        if (again.speaker === a.speaker && again.isQuestion) {
          issues.push({
            severity: "error",
            code: "qa_pingpong",
            message: `问答乒乓：${a.speaker} 提问后再次追问（夹着 ${mid.speaker} 的回答）`,
          });
          i = k;
          break;
        }
      }
      break;
    }
  }

  // 3) Too many dialogue lines for a short "stranger beat"
  if (dialogues.length >= 8) {
    issues.push({
      severity: "warn",
      code: "talk_heavy",
      message: `对白轮次偏多（${dialogues.length} 句），陌生人/克制戏宜更少更尖`,
    });
  }

  // 4) Exposition / setting dump markers
  const dumpPatterns: [RegExp, string][] = [
    [/我是.{0,12}(岁|的人|学生|职员)/, "自我介绍履历腔"],
    [/作为一名/, "说明书腔「作为一名」"],
    [/好感度/, "报好感度"],
    [/拥有.{0,8}能力/, "能力清单"],
    [/世界观|设定上/, "元设定口吻"],
  ];
  for (const [re, label] of dumpPatterns) {
    if (re.test(t)) {
      issues.push({
        severity: "error",
        code: "exposition",
        message: `疑似设定倾倒：${label}`,
      });
    }
  }

  // 5) AI cliché pile
  const cliches = [
    "微微一笑",
    "不禁",
    "涌上心头",
    "命运的齿轮",
    "空气突然安静",
    "复杂的眼神",
  ];
  const hit = cliches.filter((c) => t.includes(c));
  if (hit.length >= 2) {
    issues.push({
      severity: "warn",
      code: "cliche",
      message: `套话偏多：${hit.slice(0, 3).join("、")}`,
    });
  }

  // dedupe by code+message
  const seen = new Set<string>();
  return issues.filter((x) => {
    const k = `${x.code}:${x.message}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

export function lintHasBlockers(issues: NarrativeLintIssue[]): boolean {
  return issues.some((i) => i.severity === "error");
}
