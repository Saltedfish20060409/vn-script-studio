import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  acceptCharacterVoiceSample,
  acceptExtractedCharacterVoice,
  deleteCharacterVoiceSample,
  exportCharacterVoicePack,
  extractCharacterVoice,
  generateCharacterVoice,
  getCharacterVoiceState,
  importCharacterVoiceMind,
  rejectCharacterVoiceRound,
  synthesizeCharacterVoiceMind,
  workshopChat,
  type VoiceAxisTag,
  type VoiceScenario,
  type VoiceVariant,
} from "../api/client";
import type { VnProject, VoiceCorpusSample } from "../types/vn";
import { MascotFigure } from "./MascotFigure";
import styles from "./CharacterWorkshop.module.css";

type Props = {
  project: VnProject;
  onProjectChange: (p: VnProject) => void;
};

type Zone = "shape" | "pack" | "chat";
type ShapeMode = "preference" | "scene" | "interview" | "manual";
type ChatMode = "user" | "duo";

type GenMeta = {
  scenarioId: string;
  scenarioLabel: string;
  scenarioPrompt?: string;
  question?: string;
};

type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  speakerId?: string;
  speakerName?: string;
};

const AXIS_LETTERS = ["A", "B", "C"];
const GUIDE_STORAGE_KEY = "vnss-workshop-guide-v1";

const WHY_CHIPS = [
  "更克制",
  "关系距离对",
  "用词更像",
  "节奏对",
  "情绪对",
  "思维方式对",
] as const;

function readGuideDismissed(): boolean {
  try {
    return localStorage.getItem(GUIDE_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function linesBlock(lines: Array<{ speaker: string; text: string }>) {
  return lines.map((ln, i) => (
    <p key={i} className={styles.line}>
      <span className={styles.speaker}>
        {ln.speaker === "self"
          ? "角色"
          : ln.speaker === "other"
            ? "对方"
            : ln.speaker}
      </span>
      <span className={styles.lineText}>{ln.text}</span>
    </p>
  ));
}

function linesToText(lines: Array<{ speaker: string; text: string }>) {
  return lines
    .map((ln) => {
      const sp =
        ln.speaker === "self"
          ? "角色"
          : ln.speaker === "other"
            ? "对方"
            : ln.speaker;
      return `${sp}：${ln.text}`;
    })
    .join("\n");
}

function speakerToCorpus(sp: string): string {
  const t = sp.trim();
  if (t === "角色" || t === "本角色" || t.toLowerCase() === "self") return "self";
  if (t === "对方" || t === "对手" || t.toLowerCase() === "other") return "other";
  return t || "self";
}

function parseManualLines(text: string): Array<{ speaker: string; text: string }> {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const m = line.match(/^(.+?)[:：]\s*(.+)$/);
      if (m) return { speaker: speakerToCorpus(m[1]), text: m[2].trim() };
      return { speaker: "self", text: line };
    });
}

function parseSceneText(text: string): Array<{ speaker: string; text: string }> {
  return parseManualLines(text);
}

function ensureCustomScenario(list: VoiceScenario[]): VoiceScenario[] {
  const has = list.some((s) => s.id === "custom");
  if (has) return list;
  return [...list, { id: "custom", label: "自定义…", prompt: "", longSuitable: true }];
}

function promptSlug(prompt: string, maxLen = 16): string {
  return prompt.replace(/\s+/g, " ").trim().slice(0, maxLen);
}

const GENERIC_CUSTOM_LABELS = new Set(["", "自定义", "自定义…", "custom"]);

/** Align with backend normalize_scenario_key for coverage display */
function scenarioCoverageKey(s: VoiceCorpusSample): string {
  const sid = (s.scenario || "").trim();
  let label = (s.scenarioLabel || "").trim();
  if (label.startsWith("长场次·")) label = label.slice("长场次·".length).trim() || label;
  if (sid.startsWith("custom:")) {
    let name = sid.slice("custom:".length).trim();
    if (!name || GENERIC_CUSTOM_LABELS.has(name)) {
      name = GENERIC_CUSTOM_LABELS.has(label) ? "未命名" : label || "未命名";
    }
    return `custom:${name}`;
  }
  if (sid === "custom") {
    const name = GENERIC_CUSTOM_LABELS.has(label) ? "未命名" : label || "未命名";
    return `custom:${name}`;
  }
  return sid || label;
}

/** 与后端 corpus_stats.readyForMind 对齐的门槛说明 */
const READY_TARGETS = {
  samples: 6,
  coverage: 5,
  volume: 800,
  scenes: 2,
  interviews: 4,
  interviewVolume: 400,
} as const;

function uniqueScenarios(corpus: VoiceCorpusSample[]): string[] {
  const ids: string[] = [];
  for (const s of corpus) {
    const key = scenarioCoverageKey(s);
    if (key && !ids.includes(key)) ids.push(key);
  }
  return ids;
}

function readinessPaths(opts: {
  sampleCount: number;
  coverage: number;
  volumeChars: number;
  sceneCount: number;
  interviewCount: number;
  ready: boolean;
}): { ready: boolean; paths: string[]; nextHint: string } {
  const {
    sampleCount,
    coverage,
    volumeChars,
    sceneCount,
    interviewCount,
    ready,
  } = opts;
  const paths = [
    `短正例 ${sampleCount}/${READY_TARGETS.samples}`,
    `不同场景 ${coverage}/${READY_TARGETS.coverage}`,
    `角色台词约 ${volumeChars}/${READY_TARGETS.volume} 字`,
    `长场次 ${sceneCount}/${READY_TARGETS.scenes}`,
    `采访 ${interviewCount}/${READY_TARGETS.interviews}（且字量≥${READY_TARGETS.interviewVolume}）`,
  ];
  if (ready) {
    return {
      ready: true,
      paths,
      nextHint: "已达到合成门槛，可以去「思维包」合成了。",
    };
  }
  const remain: string[] = [];
  if (sampleCount < READY_TARGETS.samples) {
    remain.push(`再攒 ${READY_TARGETS.samples - sampleCount} 条短正例`);
  }
  if (coverage < READY_TARGETS.coverage) {
    remain.push(
      `再换 ${READY_TARGETS.coverage - coverage} 类不同场景做三选一`
    );
  }
  if (volumeChars < READY_TARGETS.volume) {
    remain.push(
      `或用长场次把台词堆到约 ${READY_TARGETS.volume} 字（还差约 ${Math.max(0, READY_TARGETS.volume - volumeChars)} 字）`
    );
  }
  if (sceneCount < READY_TARGETS.scenes) {
    remain.push(
      `或再入库 ${READY_TARGETS.scenes - sceneCount} 段长场次`
    );
  }
  return {
    ready: false,
    paths,
    nextHint: `任选一条路径凑够即可合成：${remain.slice(0, 3).join("；")}。`,
  };
}

export function CharacterWorkshop({ project, onProjectChange }: Props) {
  const characters = project.characters || [];
  const [charId, setCharId] = useState(characters[0]?.id || "");
  const character = useMemo(
    () => characters.find((c) => c.id === charId) || characters[0] || null,
    [characters, charId]
  );

  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [zone, setZone] = useState<Zone>("shape");
  const [shapeMode, setShapeMode] = useState<ShapeMode>("preference");

  const [scenarios, setScenarios] = useState<VoiceScenario[]>([]);
  const [scenarioId, setScenarioId] = useState("misunderstood");
  const [scenarioPrompt, setScenarioPrompt] = useState("");
  const [customScenarioLabel, setCustomScenarioLabel] = useState("");
  const [constraints, setConstraints] = useState("");

  const [variants, setVariants] = useState<VoiceVariant[]>([]);
  const [genMeta, setGenMeta] = useState<GenMeta | null>(null);
  const [sceneText, setSceneText] = useState("");
  const [interviewQuestion, setInterviewQuestion] = useState("");
  const [manualText, setManualText] = useState("");
  const [interviewManual, setInterviewManual] = useState("");
  const [axisTags, setAxisTags] = useState<VoiceAxisTag[]>([]);
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([]);
  const [confirmedAxes, setConfirmedAxes] = useState<string[]>([]);
  const [unlikeOpen, setUnlikeOpen] = useState(false);
  const [unlikeText, setUnlikeText] = useState("");
  const [unlikeAxis, setUnlikeAxis] = useState("");
  const [unlikeCustomAxis, setUnlikeCustomAxis] = useState("");
  const [whyOpen, setWhyOpen] = useState(false);
  const [whyChips, setWhyChips] = useState<string[]>([]);
  const [whyCustom, setWhyCustom] = useState("");
  const [pendingAccept, setPendingAccept] = useState<{
    variant: VoiceVariant;
    index: number;
    source: "preference" | "interview";
  } | null>(null);
  const [corpus, setCorpus] = useState<VoiceCorpusSample[]>([]);
  const [mind, setMind] = useState("");
  const [sampleCount, setSampleCount] = useState(0);
  const [coverage, setCoverage] = useState(0);
  const [ready, setReady] = useState(false);
  const [shortCount, setShortCount] = useState(0);
  const [sceneCount, setSceneCount] = useState(0);
  const [interviewCount, setInterviewCount] = useState(0);
  const [volumeChars, setVolumeChars] = useState(0);
  const [hasMindPack, setHasMindPack] = useState(false);
  const [showGuide, setShowGuide] = useState(() => !readGuideDismissed());
  const [dontShowGuideAgain, setDontShowGuideAgain] = useState(false);
  const [railOpen, setRailOpen] = useState(false);

  const [extractRows, setExtractRows] = useState<
    Array<{
      preview: string;
      scenarioLabel: string;
      selected: boolean;
      raw: {
        scenario: string;
        scenarioLabel: string;
        lines: Array<{ speaker: string; text: string }>;
      };
    }>
  >([]);
  const [importMd, setImportMd] = useState("");
  const [showImport, setShowImport] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(true);

  const [chatMode, setChatMode] = useState<ChatMode>("user");
  const [partnerId, setPartnerId] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [lastReplyLines, setLastReplyLines] = useState<
    Array<{ speaker: string; text: string }>
  >([]);
  const zonePanelRef = useRef<HTMLDivElement>(null);

  const partnersWithMind = useMemo(
    () =>
      characters.filter(
        (c) => c.id !== character?.id && (c.voiceMind || "").trim()
      ),
    [characters, character?.id]
  );

  useEffect(() => {
    if (!character && characters[0]) setCharId(characters[0].id);
    if (character && !characters.some((c) => c.id === charId)) {
      setCharId(characters[0]?.id || "");
    }
  }, [characters, character, charId]);

  useEffect(() => {
    if (partnersWithMind.length && !partnerId) {
      setPartnerId(partnersWithMind[0].id);
    } else if (partnerId && !partnersWithMind.some((c) => c.id === partnerId)) {
      setPartnerId(partnersWithMind[0]?.id || "");
    }
  }, [partnersWithMind, partnerId]);

  const loadState = useCallback(
    async (cid: string) => {
      if (!cid) return;
      const st = await getCharacterVoiceState(project.id, cid);
      setScenarios(ensureCustomScenario(st.scenarios || []));
      setCorpus(st.voiceCorpus || []);
      setMind(st.voiceMind || "");
      setSampleCount(st.sampleCount);
      setCoverage(st.scenarioCoverage);
      setReady(st.readyForMind);
      setShortCount(st.shortCount ?? 0);
      setSceneCount(st.sceneCount ?? 0);
      setInterviewCount(st.interviewCount ?? 0);
      setVolumeChars(st.volumeChars ?? 0);
      setHasMindPack(!!st.hasMindPack || !!(st.voiceMind || "").trim());
      setConfirmedAxes(st.confirmedAxes || []);
      if (st.axisTags?.length) setAxisTags(st.axisTags);
      if (st.scenarios?.length) {
        setScenarioId((prev) => {
          const keep = st.scenarios.find((s) => s.id === prev);
          const cur = keep || st.scenarios[0];
          setScenarioPrompt((p) => (keep && p ? p : cur.prompt));
          return cur.id;
        });
      }
    },
    [project.id]
  );

  useEffect(() => {
    if (!character?.id) return;
    let cancelled = false;
    setVariants([]);
    setGenMeta(null);
    setSceneText("");
    setInterviewQuestion("");
    setInterviewManual("");
    setSelectedTagIds([]);
    setUnlikeOpen(false);
    setError("");
    setExtractRows([]);
    setChatMessages([]);
    setLastReplyLines([]);
    (async () => {
      try {
        await loadState(character.id);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "加载角色工坊状态失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [character?.id, loadState]);

  const selectedScenario = useMemo(
    () => scenarios.find((s) => s.id === scenarioId),
    [scenarios, scenarioId]
  );

  const resolvedScenario = useMemo(() => {
    const isCustom =
      scenarioId === "custom" || scenarioId.startsWith("custom:");
    if (!isCustom) {
      return {
        id: scenarioId,
        label: selectedScenario?.label || scenarioId,
        prompt: scenarioPrompt || selectedScenario?.prompt || "",
        isCustom: false,
        longSuitable: !!selectedScenario?.longSuitable,
      };
    }
    const named = customScenarioLabel.trim();
    const slug = promptSlug(scenarioPrompt);
    const label =
      named && !GENERIC_CUSTOM_LABELS.has(named)
        ? named
        : slug || "未命名";
    return {
      id: `custom:${label}`,
      label,
      prompt: scenarioPrompt || "",
      isCustom: true,
      longSuitable: true,
    };
  }, [
    scenarioId,
    customScenarioLabel,
    selectedScenario,
    scenarioPrompt,
  ]);

  function applyProject(p: VnProject) {
    onProjectChange(p);
    const c = p.characters.find((x) => x.id === character?.id);
    if (c) {
      setCorpus(c.voiceCorpus || []);
      setMind(c.voiceMind || "");
      setSampleCount(c.voiceCorpus?.length || 0);
      setHasMindPack(!!(c.voiceMind || "").trim());
    }
  }

  function resetGen() {
    setVariants([]);
    setGenMeta(null);
    setSceneText("");
    setInterviewQuestion("");
    setInterviewManual("");
    setUnlikeOpen(false);
    setUnlikeText("");
    setUnlikeAxis("");
    setUnlikeCustomAxis("");
    setWhyOpen(false);
    setWhyChips([]);
    setWhyCustom("");
    setPendingAccept(null);
  }

  function toggleAxisTag(id: string) {
    setSelectedTagIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 3) return prev;
      return [...prev, id];
    });
  }

  async function onGenerate(constraintOverride?: string) {
    if (!character) return;
    if (resolvedScenario.isCustom && !scenarioPrompt.trim()) {
      setError("自定义场景请先填写「场景压力」（情境说明）");
      return;
    }
    setBusy("generating");
    setError("");
    // 长场次：先清结果，但保留用户正在写的压力文案
    setVariants([]);
    setGenMeta(null);
    setUnlikeOpen(false);
    if (shapeMode === "scene") setSceneText("");
    if (shapeMode === "interview") {
      /* keep question unless empty — system may fill */
    } else if (shapeMode !== "scene") {
      setInterviewQuestion("");
    }
    setInterviewManual("");
    const extra =
      constraintOverride !== undefined ? constraintOverride : constraints;
    try {
      const kind =
        shapeMode === "manual" ? "preference" : shapeMode;
      const res = await generateCharacterVoice(project.id, character.id, {
        scenario_id: resolvedScenario.id,
        scenario_prompt: resolvedScenario.prompt,
        scenario_label: resolvedScenario.label,
        extra_constraints: extra,
        kind,
        question: shapeMode === "interview" ? interviewQuestion : undefined,
        axis_tags:
          shapeMode === "preference" || shapeMode === "interview"
            ? selectedTagIds
            : undefined,
      });
      if (res.confirmedAxes) setConfirmedAxes(res.confirmedAxes);
      if (kind === "scene") {
        const lines = Array.isArray(res.lines) ? res.lines : [];
        if (!lines.length) {
          setError(
            res.variants?.length
              ? "当前后端是旧进程（忽略了 kind=scene，返回了三选一对白）。请关掉 Anaconda 的 uvicorn，只用 backend\\.venv 启动：运行项目根目录 dev.bat，或先结束占用 8000 端口的进程后再开。"
              : "长场次未返回台词，请重试。"
          );
          return;
        }
        const text = linesToText(lines);
        if (!text.trim()) {
          setError("长场次台词为空，请重试");
          return;
        }
        setSceneText(text);
        setGenMeta({
          scenarioId: res.scenarioId || resolvedScenario.id,
          scenarioLabel: res.scenarioLabel || `长场次·${resolvedScenario.label}`,
          scenarioPrompt: res.scenarioPrompt || resolvedScenario.prompt,
        });
      } else if (kind === "interview") {
        setVariants(res.variants || []);
        setInterviewQuestion(res.question || interviewQuestion || "");
        setGenMeta({
          scenarioId: res.scenarioId || "interview",
          scenarioLabel: res.scenarioLabel || "扮演采访",
          question: res.question,
        });
      } else {
        setVariants(res.variants || []);
        setGenMeta({
          scenarioId: res.scenarioId || resolvedScenario.id,
          scenarioLabel: res.scenarioLabel || resolvedScenario.label,
          scenarioPrompt: res.scenarioPrompt || resolvedScenario.prompt,
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setBusy("");
    }
  }

  function beginAcceptVariant(
    v: VoiceVariant,
    index: number,
    source: "preference" | "interview"
  ) {
    if (!character || !genMeta) return;
    setPendingAccept({ variant: v, index, source });
    setWhyChips([]);
    setWhyCustom("");
    setWhyOpen(true);
    setError("");
  }

  function renderWhyPanel() {
    if (!whyOpen || !pendingAccept) return null;
    const label =
      pendingAccept.variant.axisLabel || pendingAccept.variant.axisId || "这组";
    return (
      <div className={styles.whyBox}>
        <p className={styles.manualHint}>
          为何更像「{label}」？（可选，可跳过）填写后会进入偏好笔记，帮助后续收敛。
        </p>
        <div className={styles.tagCloud} role="group" aria-label="为何更像">
          {WHY_CHIPS.map((chip) => {
            const on = whyChips.includes(chip);
            return (
              <button
                key={chip}
                type="button"
                className={on ? styles.tagOn : styles.tag}
                aria-pressed={on}
                onClick={() => toggleWhyChip(chip)}
              >
                {chip}
              </button>
            );
          })}
        </div>
        <label className={styles.field}>
          补充一句
          <input
            value={whyCustom}
            onChange={(e) => setWhyCustom(e.target.value)}
            placeholder="例如：少卖萌，更像她对后辈的距离"
          />
        </label>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primary}
            disabled={!!busy}
            onClick={() => {
              const note = [...whyChips, whyCustom.trim()]
                .filter(Boolean)
                .join("；");
              void commitAcceptVariant(note);
            }}
          >
            {busy.startsWith("accept-") ? "写入语料…" : "确认入库"}
          </button>
          <button
            type="button"
            disabled={!!busy}
            onClick={() => void commitAcceptVariant("")}
          >
            跳过，直接入库
          </button>
          <button
            type="button"
            disabled={!!busy}
            onClick={() => {
              setWhyOpen(false);
              setPendingAccept(null);
              setWhyChips([]);
              setWhyCustom("");
            }}
          >
            取消
          </button>
        </div>
      </div>
    );
  }

  function toggleWhyChip(label: string) {
    setWhyChips((prev) =>
      prev.includes(label) ? prev.filter((x) => x !== label) : [...prev, label]
    );
  }

  async function commitAcceptVariant(preferenceNote?: string) {
    if (!character || !genMeta || !pendingAccept) return;
    const { variant: v, index, source } = pendingAccept;
    setBusy(`accept-${index}`);
    setError("");
    try {
      const rejected = variants
        .filter((_, i) => i !== index)
        .map((x) => x.hypothesis || x.axisLabel)
        .filter(Boolean)
        .join(" / ");
      const note = (preferenceNote || "").trim();
      const res = await acceptCharacterVoiceSample(project.id, character.id, {
        scenario_id: genMeta.scenarioId,
        scenario_label: genMeta.scenarioLabel,
        scenario_prompt: genMeta.scenarioPrompt,
        axis: v.axisLabel || v.axisId,
        hypothesis: v.hypothesis,
        lines: v.lines,
        rejected_summary: rejected || undefined,
        preference_note: note || undefined,
        user_note: note || undefined,
        source,
      });
      applyProject(res.project);
      setSampleCount(res.sampleCount);
      setCoverage(res.scenarioCoverage);
      setReady(res.readyForMind);
      resetGen();
      await loadState(character.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "入库失败");
    } finally {
      setBusy("");
    }
  }

  async function onAcceptVariant(
    v: VoiceVariant,
    index: number,
    source: "preference" | "interview"
  ) {
    beginAcceptVariant(v, index, source);
  }

  async function onAcceptScene() {
    if (!character) return;
    const lines = parseSceneText(sceneText);
    if (!lines.length) {
      setError("请先填写或生成场次台词");
      return;
    }
    const meta = genMeta || {
      scenarioId: resolvedScenario.id,
      scenarioLabel: `长场次·${resolvedScenario.label}`,
      scenarioPrompt: resolvedScenario.prompt,
    };
    setBusy("accept-scene");
    setError("");
    try {
      const res = await acceptCharacterVoiceSample(project.id, character.id, {
        scenario_id: meta.scenarioId,
        scenario_label: meta.scenarioLabel,
        scenario_prompt: meta.scenarioPrompt,
        lines,
        source: "scene",
      });
      applyProject(res.project);
      setSampleCount(res.sampleCount);
      setCoverage(res.scenarioCoverage);
      setReady(res.readyForMind);
      resetGen();
      await loadState(character.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "入库失败");
    } finally {
      setBusy("");
    }
  }

  async function onAcceptManual(source: "manual" | "interview") {
    if (!character) return;
    const text = source === "interview" ? interviewManual : manualText;
    const lines = parseManualLines(text);
    if (!lines.length) {
      setError("请先输入台词");
      return;
    }
    setBusy(`accept-${source}`);
    setError("");
    try {
      const res = await acceptCharacterVoiceSample(project.id, character.id, {
        scenario_id:
          source === "interview" ? "interview" : resolvedScenario.id,
        scenario_label:
          source === "interview"
            ? `采访·${(genMeta?.question || interviewQuestion || "手动").slice(0, 20)}`
            : resolvedScenario.label,
        scenario_prompt:
          source === "interview" ? undefined : resolvedScenario.prompt,
        lines,
        source,
      });
      applyProject(res.project);
      setSampleCount(res.sampleCount);
      setCoverage(res.scenarioCoverage);
      setReady(res.readyForMind);
      if (source === "manual") setManualText("");
      if (source === "interview") setInterviewManual("");
      await loadState(character.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "入库失败");
    } finally {
      setBusy("");
    }
  }

  async function onRejectAll() {
    if (!character) return;
    // Open「都不像」handwrite panel; still record reject notes
    setBusy("reject");
    setError("");
    try {
      const res = await rejectCharacterVoiceRound(project.id, character.id, {
        hypotheses: variants.map((v) => v.hypothesis || v.axisLabel),
        note: constraints
          ? `都不像；请收紧：${constraints}`
          : "三组都不符合预期，改用手写",
      });
      applyProject(res.project);
      setUnlikeAxis(variants[0]?.axisLabel || "");
      setUnlikeCustomAxis("");
      setUnlikeText("");
      setUnlikeOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "记录失败");
    } finally {
      setBusy("");
    }
  }

  async function onAcceptUnlike() {
    if (!character || !genMeta) return;
    const lines = parseManualLines(unlikeText);
    if (!lines.length) {
      setError("请先手写更像的台词");
      return;
    }
    const axis =
      unlikeCustomAxis.trim() ||
      unlikeAxis.trim() ||
      variants[0]?.axisLabel ||
      "手写方向";
    setBusy("accept-unlike");
    setError("");
    try {
      const res = await acceptCharacterVoiceSample(project.id, character.id, {
        scenario_id: genMeta.scenarioId,
        scenario_label: genMeta.scenarioLabel,
        scenario_prompt: genMeta.scenarioPrompt,
        axis,
        hypothesis: `手写补方向：${axis}`,
        lines,
        rejected_summary: variants
          .map((v) => v.hypothesis || v.axisLabel)
          .filter(Boolean)
          .join(" / "),
        source: "preference",
      });
      applyProject(res.project);
      setSampleCount(res.sampleCount);
      setCoverage(res.scenarioCoverage);
      setReady(res.readyForMind);
      setConfirmedAxes((prev) =>
        prev.includes(axis) ? prev : [...prev, axis].slice(-8)
      );
      resetGen();
      await loadState(character.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "入库失败");
    } finally {
      setBusy("");
    }
  }

  async function onDeleteSample(id: string) {
    if (!character) return;
    setBusy(`del-${id}`);
    setError("");
    try {
      const res = await deleteCharacterVoiceSample(project.id, character.id, id);
      applyProject(res.project);
      setSampleCount(res.sampleCount);
      await loadState(character.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy("");
    }
  }

  async function onSynthesize(force: boolean) {
    if (!character) return;
    setBusy("synth");
    setError("");
    try {
      const res = await synthesizeCharacterVoiceMind(project.id, character.id, {
        force,
        apply_voice_summary: true,
      });
      applyProject(res.project);
      setMind(res.markdown);
      setReady(res.ready);
      setHasMindPack(true);
      setZone("pack");
    } catch (e) {
      setError(e instanceof Error ? e.message : "合成失败");
    } finally {
      setBusy("");
    }
  }

  async function onExtract() {
    if (!character) return;
    setBusy("extract");
    setError("");
    setDrawerOpen(true);
    try {
      const res = await extractCharacterVoice(project.id, character.id);
      setExtractRows(
        (res.candidates || []).map((c) => ({
          preview: c.preview,
          scenarioLabel: c.scenarioLabel,
          selected: false,
          raw: {
            scenario: c.scenario,
            scenarioLabel: c.scenarioLabel,
            lines: c.lines,
          },
        }))
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "抽取失败");
    } finally {
      setBusy("");
    }
  }

  async function onAcceptExtract() {
    if (!character) return;
    const samples = extractRows.filter((r) => r.selected).map((r) => r.raw);
    if (!samples.length) {
      setError("请先勾选要加入的对白");
      return;
    }
    setBusy("extract-accept");
    setError("");
    try {
      const res = await acceptExtractedCharacterVoice(project.id, character.id, {
        samples,
      });
      applyProject(res.project);
      setSampleCount(res.sampleCount);
      setCoverage(res.scenarioCoverage);
      setReady(res.readyForMind);
      setExtractRows([]);
      await loadState(character.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加入失败");
    } finally {
      setBusy("");
    }
  }

  async function onExport() {
    if (!character) return;
    setBusy("export");
    setError("");
    try {
      const pack = await exportCharacterVoicePack(project.id, character.id);
      const blob = new Blob([pack.markdown], {
        type: "text/markdown;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = pack.filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
    } finally {
      setBusy("");
    }
  }

  async function onImportMind() {
    if (!character) return;
    if (!importMd.trim()) {
      setError("请粘贴思维包 markdown");
      return;
    }
    setBusy("import");
    setError("");
    try {
      const res = await importCharacterVoiceMind(project.id, character.id, {
        markdown: importMd,
      });
      applyProject(res.project);
      setMind(res.voiceMind || "");
      setHasMindPack(!!(res.voiceMind || "").trim());
      setShowImport(false);
      setImportMd("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "导入失败");
    } finally {
      setBusy("");
    }
  }

  function chatHistoryPayload(msgs: ChatMsg[]) {
    return msgs.map((m) => ({
      role: m.role === "user" ? "user" : "assistant",
      content: m.speakerName
        ? `${m.speakerName}：${m.content}`
        : m.content,
    }));
  }

  async function onSendChat() {
    if (!character || !chatInput.trim()) return;
    setBusy("chat");
    setError("");
    const userMsg: ChatMsg = {
      id: `u-${Date.now()}`,
      role: "user",
      content: chatInput.trim(),
    };
    const nextMsgs = [...chatMessages, userMsg];
    setChatMessages(nextMsgs);
    setChatInput("");
    try {
      const res = await workshopChat(project.id, character.id, {
        mode: chatMode,
        message: userMsg.content,
        partner_id: chatMode === "duo" ? partnerId : undefined,
        history: chatHistoryPayload(chatMessages),
      });
      if (chatMode === "duo" && res.lines?.length) {
        const newMsgs: ChatMsg[] = res.lines.map((ln, i) => ({
          id: `a-${Date.now()}-${i}`,
          role: "assistant" as const,
          content: ln.text,
          speakerId: ln.speakerId,
          speakerName: ln.speakerName,
        }));
        setChatMessages([...nextMsgs, ...newMsgs]);
        const focusLines = res.lines
          .filter((ln) => ln.speakerId === character.id)
          .map((ln) => ({ speaker: "self", text: ln.text }));
        setLastReplyLines(
          focusLines.length
            ? focusLines
            : res.lines.map((ln) => ({
                speaker: ln.speakerId === character.id ? "self" : "other",
                text: ln.text,
              }))
        );
      } else if (res.reply) {
        const replyMsg: ChatMsg = {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: res.reply,
          speakerId: res.speakerId,
          speakerName: res.speakerName,
        };
        setChatMessages([...nextMsgs, replyMsg]);
        setLastReplyLines([{ speaker: "self", text: res.reply }]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "对话失败");
      setChatMessages(chatMessages);
    } finally {
      setBusy("");
    }
  }

  async function onSaveChatAsSample() {
    if (!character || !lastReplyLines.length) {
      setError("尚无角色回复可存入");
      return;
    }
    setBusy("save-chat");
    setError("");
    try {
      const res = await acceptCharacterVoiceSample(project.id, character.id, {
        scenario_id: "chat",
        scenario_label: "工坊对话",
        lines: lastReplyLines,
        source: "chat",
      });
      applyProject(res.project);
      setSampleCount(res.sampleCount);
      setCoverage(res.scenarioCoverage);
      setReady(res.readyForMind);
      await loadState(character.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "存入失败");
    } finally {
      setBusy("");
    }
  }

  function renderScenarioControls(showGenerate = true) {
    const list = ensureCustomScenario(
      scenarios.length
        ? scenarios
        : [{ id: "misunderstood", label: "被误解时", prompt: "" }]
    );
    const isCustom =
      scenarioId === "custom" || scenarioId.startsWith("custom:");
    return (
      <div className={styles.controls}>
        <label className={styles.field}>
          场景
          <select
            value={isCustom ? "custom" : scenarioId}
            onChange={(e) => {
              const id = e.target.value;
              setScenarioId(id);
              const sc = list.find((s) => s.id === id);
              if (id === "custom") {
                if (!scenarioPrompt.trim()) setScenarioPrompt("");
              } else if (sc) {
                setScenarioPrompt(sc.prompt);
              }
            }}
          >
            {list.map((s) => (
              <option key={s.id} value={s.id}>
                {s.longSuitable && shapeMode === "scene" ? "宜写长 · " : ""}
                {s.label}
              </option>
            ))}
          </select>
        </label>
        {isCustom && (
          <label className={styles.field}>
            自定义名称
            <input
              value={customScenarioLabel}
              onChange={(e) => setCustomScenarioLabel(e.target.value)}
              placeholder="例如：雨夜车站分别（建议填写，计入不同场景）"
            />
          </label>
        )}
        {isCustom && !customScenarioLabel.trim() && scenarioPrompt.trim() && (
          <p className={styles.scenarioHint}>
            未起名时将按压力文案记为「{promptSlug(scenarioPrompt)}」，仍计入覆盖。
          </p>
        )}
        {shapeMode === "scene" && !isCustom && (
          <p className={styles.scenarioHint}>
            {resolvedScenario.longSuitable
              ? "此场景较宜写长：关系推进或压力可持续多轮。"
              : "此场景偏短压测；长场次也能用，但戏幅可能偏紧。可换带「宜写长」标记的场景。"}
          </p>
        )}
        {shapeMode === "scene" && isCustom && (
          <p className={styles.scenarioHint}>
            自定义场景默认宜写长：把情境写清，方便多轮推进。
          </p>
        )}
        <label className={`${styles.field} ${styles.grow}`}>
          场景压力
          <textarea
            rows={2}
            value={scenarioPrompt}
            onChange={(e) => setScenarioPrompt(e.target.value)}
            placeholder={
              isCustom
                ? "用一两句话写清情境与压力（必填；可兼作场景名）"
                : "可改写默认压力，或保持预设"
            }
          />
        </label>
        <label className={styles.field}>
          额外约束
          <input
            value={constraints}
            onChange={(e) => setConstraints(e.target.value)}
            placeholder="再短一点；禁止卖萌"
          />
        </label>
        {showGenerate && (
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              disabled={!!busy || !character}
              onClick={() => void onGenerate()}
            >
              {busy === "generating" ? "生成中…" : generateLabel()}
            </button>
            {shapeMode === "preference" && variants.length > 0 && (
              <button
                type="button"
                disabled={!!busy}
                onClick={() => void onRejectAll()}
              >
                都不像…
              </button>
            )}
            {shapeMode === "preference" && selectedTagIds.length > 0 && (
              <button
                type="button"
                disabled={!!busy || !character}
                onClick={() => void onGenerate()}
                title="按已勾标签重开三组"
              >
                按标签重开
              </button>
            )}
            {shapeMode === "preference" && sampleCount >= 1 && (
              <button
                type="button"
                disabled={!!busy}
                onClick={() => {
                  const next = constraints.includes("对齐已选正例")
                    ? constraints
                    : [constraints, "必须对齐已选正例与思维包；禁止换人设"]
                        .filter(Boolean)
                        .join("；");
                  setConstraints(next);
                  void onGenerate(next);
                }}
              >
                同场景试写
              </button>
            )}
          </div>
        )}
      </div>
    );
  }

  function generateLabel() {
    switch (shapeMode) {
      case "scene":
        return "生成长场次";
      case "interview":
        return "生成三组回答";
      default:
        return "生成三组";
    }
  }

  function renderShapeZone() {
    return (
      <>
        <div className={styles.shapeModes}>
          {(
            [
              ["preference", "三选一"],
              ["scene", "长场次"],
              ["interview", "扮演采访"],
              ["manual", "手写金句"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={
                shapeMode === id ? styles.shapeModeOn : styles.shapeMode
              }
              onClick={() => {
                setShapeMode(id);
                resetGen();
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {shapeMode !== "manual" && renderScenarioControls()}

        {shapeMode === "preference" && (
          <p className={styles.shapeTip}>
            默认按角色卡出本轮三轴；侧边可勾最多 3 个标签后「按标签重开」。少选时模型补轴。
            多换<strong>场景</strong>收敛方向。
            {confirmedAxes.length > 0 && (
              <>
                {" "}
                已确认：
                <em>{confirmedAxes.join(" · ")}</em>
              </>
            )}
            {uniqueScenarios(corpus).length > 0 && (
              <>
                {" "}
                已覆盖 <em>{uniqueScenarios(corpus).length}</em> 类场景。
              </>
            )}
          </p>
        )}

        {(shapeMode === "preference" || shapeMode === "interview") &&
          axisTags.length > 0 && (
          <div className={styles.tagPanel}>
            <div className={styles.tagPanelHead}>
              <span>方向标签（可选，最多 3）</span>
              {selectedTagIds.length > 0 && (
                <button
                  type="button"
                  className={styles.tagClear}
                  onClick={() => setSelectedTagIds([])}
                >
                  清空
                </button>
              )}
            </div>
            <div className={styles.tagCloud} role="group" aria-label="方向标签">
              {axisTags.map((t) => {
                const on = selectedTagIds.includes(t.id);
                return (
                  <button
                    key={t.id}
                    type="button"
                    className={on ? styles.tagOn : styles.tag}
                    title={t.hint}
                    aria-pressed={on}
                    onClick={() => toggleAxisTag(t.id)}
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {shapeMode === "preference" && sampleCount > 0 && !ready && (
          <div className={styles.readyBannerCompact}>
            {renderReadinessBanner({ compact: true })}
          </div>
        )}

        {shapeMode === "interview" && (
          <label className={`${styles.field} ${styles.grow}`}>
            采访问题（可留空由系统出题）
            <input
              value={interviewQuestion}
              onChange={(e) => setInterviewQuestion(e.target.value)}
              placeholder="例如：你最怕别人发现你哪一点？"
            />
          </label>
        )}

        {shapeMode === "preference" && (
          <div className={styles.cardStage}>
            {variants.length === 0 && !busy && (
              <div className={styles.emptyStage}>
                <p>定声音</p>
                <span>
                  选场景 → 生成三组（动态轴）→ 选最像的入库。都不像可手写并记方向。
                </span>
                <button
                  type="button"
                  className={styles.primary}
                  disabled={!!busy || !character}
                  onClick={() => void onGenerate()}
                >
                  生成三组
                </button>
              </div>
            )}
            {busy === "generating" && (
              <div className={styles.busyBar} role="status" aria-live="polite">
                <span className={styles.busyStamp} aria-hidden>
                  RUN
                </span>
                <span className={styles.busyPulse} aria-hidden />
                <span>生成进行中…按本轮三轴拉开差异</span>
              </div>
            )}
            {variants.length > 0 && (
              <div className={styles.variantGrid}>
                {variants.map((v, i) => (
                  <article key={v.axisId + i} className={styles.variantCard}>
                    <div className={styles.cardLetter}>
                      {AXIS_LETTERS[i] || i + 1}
                    </div>
                    <header className={styles.cardHead}>
                      <h3>{v.axisLabel || v.axisId}</h3>
                      <p>{v.hypothesis}</p>
                    </header>
                    <div className={styles.cardBody}>{linesBlock(v.lines)}</div>
                    <footer className={styles.cardFoot}>
                      <button
                        type="button"
                        className={styles.primary}
                        disabled={!!busy}
                        onClick={() => void onAcceptVariant(v, i, "preference")}
                      >
                        {busy === `accept-${i}` ? "写入语料…" : "选这组入库"}
                      </button>
                    </footer>
                  </article>
                ))}
              </div>
            )}
            {renderWhyPanel()}
            {unlikeOpen && (
              <div className={styles.unlikeBox}>
                <p className={styles.manualHint}>
                  都不像：手写更贴的对白，并确认本轮<strong>方向标签</strong>
                  （可从本轮三轴选，或自填）。
                </p>
                <div className={styles.unlikeAxes}>
                  {variants.map((v) => (
                    <button
                      key={v.axisId}
                      type="button"
                      className={
                        unlikeAxis === v.axisLabel && !unlikeCustomAxis.trim()
                          ? styles.tagOn
                          : styles.tag
                      }
                      onClick={() => {
                        setUnlikeAxis(v.axisLabel || v.axisId);
                        setUnlikeCustomAxis("");
                      }}
                    >
                      {v.axisLabel || v.axisId}
                    </button>
                  ))}
                </div>
                <label className={styles.field}>
                  或自填方向
                  <input
                    value={unlikeCustomAxis}
                    onChange={(e) => setUnlikeCustomAxis(e.target.value)}
                    placeholder="例如：温柔劝说"
                  />
                </label>
                <textarea
                  rows={4}
                  value={unlikeText}
                  onChange={(e) => setUnlikeText(e.target.value)}
                  placeholder={"对方：……\n角色：……"}
                />
                <div className={styles.actions}>
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={!!busy || !unlikeText.trim()}
                    onClick={() => void onAcceptUnlike()}
                  >
                    {busy === "accept-unlike" ? "入库中…" : "手写入库"}
                  </button>
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => {
                      setUnlikeOpen(false);
                      resetGen();
                      if (!constraints)
                        setConstraints("再短一点；少卖萌；少书面语");
                    }}
                  >
                    丢弃并重开
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {shapeMode === "scene" && (
          <div className={styles.sceneEditor}>
            {busy === "generating" ? (
              <div className={styles.busyBar} role="status" aria-live="polite">
                <span className={styles.busyStamp} aria-hidden>
                  RUN
                </span>
                <span className={styles.busyPulse} aria-hidden />
                <span>生成进行中…长场次约需数十秒</span>
              </div>
            ) : sceneText.trim() ? (
              <>
                <p className={styles.muted}>
                  生成后可编辑台词，确认无误后整段入库。
                </p>
                <textarea
                  value={sceneText}
                  onChange={(e) => setSceneText(e.target.value)}
                  placeholder="角色：第一句&#10;对方：回应&#10;…"
                />
                <div className={styles.actions}>
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={!!busy || !sceneText.trim()}
                    onClick={() => void onAcceptScene()}
                  >
                    {busy === "accept-scene" ? "入库中…" : "整段入库"}
                  </button>
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => void onGenerate()}
                  >
                    重新生成
                  </button>
                </div>
              </>
            ) : (
              <div className={styles.emptyStage}>
                <p>长场次加厚</p>
                <span>
                  一次约 8～12 轮，整段入库。无结果时看底部错误提示。
                </span>
                <button
                  type="button"
                  className={styles.primary}
                  disabled={!!busy || !character}
                  onClick={() => void onGenerate()}
                >
                  生成长场次
                </button>
              </div>
            )}
          </div>
        )}

        {shapeMode === "interview" && (
          <>
            {(interviewQuestion || genMeta?.question) && (
              <p className={styles.interviewQ}>
                {interviewQuestion || genMeta?.question}
              </p>
            )}
            <div className={styles.cardStage}>
              {variants.length === 0 && !busy && (
                <div className={styles.emptyStage}>
                  <p>扮演采访</p>
                  <span>出一道压力题，生成三组回答，挑最像本音的入库。</span>
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={!!busy || !character}
                    onClick={() => void onGenerate()}
                  >
                    生成三组回答
                  </button>
                </div>
              )}
              {busy === "generating" && (
                <div className={styles.busyBar} role="status" aria-live="polite">
                  <span className={styles.busyStamp} aria-hidden>
                    RUN
                  </span>
                  <span className={styles.busyPulse} aria-hidden />
                  <span>生成进行中…角色正在组织回答</span>
                </div>
              )}
              {variants.length > 0 && (
                <div className={styles.variantGrid}>
                  {variants.map((v, i) => (
                    <article key={v.axisId + i} className={styles.variantCard}>
                      <div className={styles.cardLetter}>
                        {AXIS_LETTERS[i] || i + 1}
                      </div>
                      <header className={styles.cardHead}>
                        <h3>{v.axisLabel || v.axisId}</h3>
                        <p>{v.hypothesis}</p>
                      </header>
                      <div className={styles.cardBody}>
                        {linesBlock(v.lines)}
                      </div>
                      <footer className={styles.cardFoot}>
                        <button
                          type="button"
                          className={styles.primary}
                          disabled={!!busy}
                          onClick={() =>
                            void onAcceptVariant(v, i, "interview")
                          }
                        >
                          {busy === `accept-${i}` ? "写入语料…" : "选这组入库"}
                        </button>
                      </footer>
                    </article>
                  ))}
                </div>
              )}
              {renderWhyPanel()}
            </div>
            <div className={styles.manualBox}>
              <p className={styles.manualHint}>
                或手写回答（一行或多行），作为采访正例入库
              </p>
              <textarea
                rows={4}
                value={interviewManual}
                onChange={(e) => setInterviewManual(e.target.value)}
                placeholder="直接写角色会怎么答…"
              />
              <button
                type="button"
                className={styles.primary}
                disabled={!!busy || !interviewManual.trim()}
                onClick={() => void onAcceptManual("interview")}
              >
                {busy === "accept-interview" ? "入库中…" : "手写回答入库"}
              </button>
            </div>
          </>
        )}

        {shapeMode === "manual" && (
          <div className={styles.manualBox}>
            <p className={styles.manualHint}>
              每行一句，或「角色：台词」格式；直接作为金句正例入库
            </p>
            {renderScenarioControls(false)}
            <textarea
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              placeholder={"短句一\n角色：短句二"}
            />
            <button
              type="button"
              className={styles.primary}
              disabled={!!busy || !manualText.trim()}
              onClick={() => void onAcceptManual("manual")}
            >
              {busy === "accept-manual" ? "入库中…" : "金句入库"}
            </button>
          </div>
        )}

        <div className={styles.drawer}>
          <div className={styles.drawerTabs}>
            <button
              type="button"
              className={drawerOpen ? styles.drawerTabOn : styles.drawerTab}
              onClick={() => setDrawerOpen((v) => !v)}
            >
              语料库 ({sampleCount}) · 抽取工具
            </button>
          </div>
          {drawerOpen && (
            <div className={styles.drawerBody}>
              <div className={styles.actions}>
                <button
                  type="button"
                  disabled={!!busy}
                  onClick={() => void onExtract()}
                >
                  从剧本抽取
                </button>
              </div>
              {corpus.length === 0 ? (
                <p className={styles.muted}>尚未入库。塑形后正例会出现在这里。</p>
              ) : (
                <ul className={styles.corpusList}>
                  {corpus.map((s) => (
                    <li key={s.id}>
                      <div>
                        <strong>{s.scenarioLabel || s.scenario}</strong>
                        {s.source ? ` · ${s.source}` : ""}
                        {s.axis ? ` · ${s.axis}` : ""}
                        <div className={styles.mini}>
                          {(s.lines || [])
                            .map((l) => l.text)
                            .filter(Boolean)
                            .join(" / ")}
                        </div>
                      </div>
                      <button
                        type="button"
                        className={styles.danger}
                        disabled={!!busy}
                        onClick={() => void onDeleteSample(s.id)}
                      >
                        删
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {extractRows.length > 0 && (
                <div className={styles.extract}>
                  <ul>
                    {extractRows.map((r, i) => (
                      <li key={i}>
                        <label>
                          <input
                            type="checkbox"
                            checked={r.selected}
                            onChange={(e) => {
                              const next = [...extractRows];
                              next[i] = { ...r, selected: e.target.checked };
                              setExtractRows(next);
                            }}
                          />
                          <span>
                            [{r.scenarioLabel}] {r.preview}
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={!!busy}
                    onClick={() => void onAcceptExtract()}
                  >
                    加入所选
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </>
    );
  }

  function renderReadinessBanner(opts?: { compact?: boolean }) {
    const unique = uniqueScenarios(corpus);
    const info = readinessPaths({
      sampleCount,
      coverage,
      volumeChars,
      sceneCount,
      interviewCount,
      ready,
    });
    const narrow =
      sampleCount >= 2 && unique.length <= 1
        ? "目前语料几乎只来自同一场景，形象容易片面。请换几个压力场景再做三选一（被误解 / 别扭关心 / 面对权威等）。"
        : unique.length > 0 && unique.length < 3 && sampleCount >= 3
          ? `已覆盖 ${unique.length} 类场景。建议至少再换 2～3 个不同场景，对白感觉会稳很多。`
          : "";

    return (
      <div
        className={
          info.ready ? styles.readyBannerOk : styles.readyBanner
        }
      >
        <p className={styles.readyTitle}>
          {info.ready
            ? "可以合成思维包了"
            : "合成门槛（满足任一路径即可）"}
        </p>
        {!opts?.compact && (
          <ul className={styles.readyPaths}>
            {info.paths.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        <p className={styles.readyHint}>{info.nextHint}</p>
        {narrow && <p className={styles.readyWarn}>{narrow}</p>}
        {!info.ready && (
          <p className={styles.readyTip}>
            小技巧：三选一请<strong>切换不同场景</strong>
            再生成，不要只改「场景压力」却一直停在同一类情境——否则思维包会偏窄。
          </p>
        )}
      </div>
    );
  }

  function renderPackZone() {
    return (
      <div className={styles.packZone}>
        <p className={styles.muted}>
          思维包由正例语料蒸馏而来，写剧本与对话时 Agent 会参照其中的口吻规则。
        </p>
        {renderReadinessBanner()}
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primary}
            disabled={!!busy || sampleCount < 1 || (!ready && busy !== "synth")}
            title={
              !ready
                ? "未达推荐门槛时可点「强制合成」，但质量可能偏差"
                : undefined
            }
            onClick={() => void onSynthesize(false)}
          >
            {busy === "synth" ? "合成中…" : "合成思维包"}
          </button>
          <button
            type="button"
            disabled={!!busy || sampleCount < 1}
            onClick={() => void onSynthesize(true)}
            title="样本不足时也可强制，建议先换场景多攒几条"
          >
            强制合成
          </button>
          <button
            type="button"
            disabled={!!busy}
            onClick={() => void onExport()}
          >
            导出女娲包
          </button>
          <button
            type="button"
            disabled={!!busy}
            onClick={() => setShowImport((v) => !v)}
          >
            导入思维包
          </button>
        </div>
        {!ready && sampleCount >= 1 && (
          <p className={styles.muted}>
            未达门槛时「合成思维包」会失败；可用「强制合成」，但更推荐先换场景补语料。
          </p>
        )}
        {showImport && (
          <div className={styles.importBox}>
            <textarea
              rows={6}
              value={importMd}
              onChange={(e) => setImportMd(e.target.value)}
              placeholder="粘贴女娲蒸馏后的 SKILL.md / 思维包 markdown…"
            />
            <button
              type="button"
              className={styles.primary}
              disabled={!!busy}
              onClick={() => void onImportMind()}
            >
              确认导入
            </button>
          </div>
        )}
        {mind ? (
          <pre className={styles.mindPre}>{mind}</pre>
        ) : (
          <p className={styles.muted}>
            还没有思维包。凑够上方门槛后点合成，或导入已有女娲包。
          </p>
        )}
      </div>
    );
  }

  function renderChatZone() {
    if (!hasMindPack) {
      return (
        <div className={styles.chatLock}>
          <p>需要先合成或导入思维包</p>
          <button
            type="button"
            className={styles.primary}
            onClick={() => setZone("pack")}
          >
            前往思维包
          </button>
        </div>
      );
    }

    return (
      <div className={styles.chatPanel}>
        <div className={styles.chatModes}>
          <button
            type="button"
            className={chatMode === "user" ? styles.shapeModeOn : styles.shapeMode}
            onClick={() => setChatMode("user")}
          >
            与 TA 聊
          </button>
          <button
            type="button"
            className={chatMode === "duo" ? styles.shapeModeOn : styles.shapeMode}
            onClick={() => setChatMode("duo")}
          >
            角色互聊
          </button>
          {chatMode === "duo" && (
            <label className={styles.field} style={{ marginLeft: "auto" }}>
              搭档
              <select
                value={partnerId}
                onChange={(e) => setPartnerId(e.target.value)}
              >
                {partnersWithMind.length === 0 ? (
                  <option value="">无可用角色</option>
                ) : (
                  partnersWithMind.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.displayName}
                    </option>
                  ))
                )}
              </select>
            </label>
          )}
        </div>

        <div className={styles.chatLog}>
          {chatMessages.length === 0 && (
            <p className={styles.muted}>
              {chatMode === "duo"
                ? "输入旁白或出题，看两位角色如何交锋。"
                : "输入一句话，看看角色会怎么回。"}
            </p>
          )}
          {chatMessages.map((m) => (
            <div
              key={m.id}
              className={`${styles.bubble} ${
                m.role === "user" ? styles.bubbleSelf : styles.bubbleOther
              }`}
            >
              {m.speakerName && m.role !== "user" && (
                <span className={styles.bubbleName}>{m.speakerName}</span>
              )}
              {m.content}
            </div>
          ))}
        </div>

        <div className={styles.chatToolbar}>
          <button
            type="button"
            disabled={!!busy}
            onClick={() => {
              setChatMessages([]);
              setLastReplyLines([]);
            }}
          >
            清空会话
          </button>
          <button
            type="button"
            disabled={!!busy || !lastReplyLines.length}
            onClick={() => void onSaveChatAsSample()}
          >
            {busy === "save-chat" ? "存入中…" : "存入正例"}
          </button>
        </div>

        <div className={styles.chatInput}>
          <textarea
            rows={2}
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            placeholder={
              chatMode === "duo" ? "旁白 / 出题…" : "对角色说…"
            }
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void onSendChat();
              }
            }}
          />
          <button
            type="button"
            className={styles.primary}
            disabled={!!busy || !chatInput.trim()}
            onClick={() => void onSendChat()}
          >
            {busy === "chat" ? "…" : "发送"}
          </button>
        </div>
      </div>
    );
  }

  function dismissGuide() {
    if (dontShowGuideAgain) {
      try {
        localStorage.setItem(GUIDE_STORAGE_KEY, "1");
      } catch {
        /* ignore */
      }
    }
    setShowGuide(false);
  }

  function goStep(next: Zone) {
    setZone(next);
    if (next === "shape") setShapeMode("preference");
    // 等分区切换渲染后再滚到主内容，保证能看到该区全貌
    window.setTimeout(() => {
      const el = zonePanelRef.current;
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "start", inline: "nearest" });
      // 若外层 main/壳层是滚动容器，再补一次定位
      const scroller = el.closest("[data-workshop-scroll], main, .shell") as
        | HTMLElement
        | null;
      if (scroller && scroller !== el && scroller.scrollHeight > scroller.clientHeight) {
        const top =
          el.getBoundingClientRect().top -
          scroller.getBoundingClientRect().top +
          scroller.scrollTop -
          12;
        scroller.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      }
    }, 40);
  }

  function renderProgress() {
    const steps: Array<{
      id: Zone;
      title: string;
      desc: string;
      done: boolean;
      cta: string;
    }> = [
      {
        id: "shape",
        title: "① 定声音",
        desc:
          sampleCount > 0
            ? `已有 ${sampleCount} 条 · ${uniqueScenarios(corpus).length} 类场景` +
              (uniqueScenarios(corpus).length <= 1 && sampleCount >= 2
                ? "（偏窄，请换场景）"
                : "")
            : "建议多场景三选一，勿单场景刷",
        done: sampleCount > 0,
        cta: sampleCount > 0 ? "继续塑形" : "开始塑形",
      },
      {
        id: "pack",
        title: "② 出思维包",
        desc: hasMindPack
          ? "已解锁对话"
          : ready
            ? "已达门槛，可以合成"
            : readinessPaths({
                sampleCount,
                coverage,
                volumeChars,
                sceneCount,
                interviewCount,
                ready,
              }).nextHint,
        done: hasMindPack,
        cta: hasMindPack ? "查看思维包" : "去合成",
      },
      {
        id: "chat",
        title: "③ 试聊排练",
        desc: hasMindPack
          ? "与角色聊或角色互聊"
          : "需先有思维包",
        done: hasMindPack,
        cta: hasMindPack ? "去试聊" : "先完成思维包",
      },
    ];
    const next = steps.find((s) => !s.done) || steps[2];

    const doneCount = steps.filter((s) => s.done).length;
    const pct = Math.round((doneCount / steps.length) * 100);

    return (
      <div className={styles.progress}>
        <div className={styles.progressRail} aria-label={`进度 ${doneCount}/3`}>
          <div className={styles.progressRailTop}>
                <span>档案养成</span>
            <strong>
              {doneCount}/3 · {next.title.replace(/^[①②③]\s*/, "")}
            </strong>
          </div>
          <div className={styles.progressRailTrack}>
            <div className={styles.progressRailFill} style={{ width: `${pct}%` }} />
          </div>
          <div className={styles.progressRailSteps}>
            {steps.map((s) => (
              <button
                key={s.id}
                type="button"
                className={
                  s.done
                    ? styles.progressDotDone
                    : s.id === next.id
                      ? styles.progressDotOn
                      : styles.progressDot
                }
                disabled={s.id === "chat" && !hasMindPack}
                onClick={() => goStep(s.id)}
                title={s.title}
              >
                {s.title.replace(/^([①②③]).*/, "$1")}
              </button>
            ))}
          </div>
        </div>
        <ol className={styles.progressList}>
          {steps.map((s) => (
            <li
              key={s.id}
              className={
                s.done
                  ? styles.progressDone
                  : s.id === next.id
                    ? styles.progressCurrent
                    : styles.progressItem
              }
            >
              <button
                type="button"
                className={styles.progressJump}
                disabled={s.id === "chat" && !hasMindPack}
                onClick={() => goStep(s.id)}
              >
                <strong>{s.title}</strong>
                <span>{s.desc}</span>
              </button>
              {s.id === next.id ? (
                <button
                  type="button"
                  className={styles.primary}
                  disabled={s.id === "chat" && !hasMindPack}
                  onClick={() => goStep(s.id)}
                >
                  {s.cta}
                </button>
              ) : null}
            </li>
          ))}
        </ol>
      </div>
    );
  }

  function renderGuide() {
    if (!showGuide) return null;
    return (
      <div className={styles.guideOverlay} role="dialog" aria-modal="true">
        <div className={styles.guideCard}>
          <div className={styles.guideMascot} aria-hidden>
            <MascotFigure size="lg" mood="cheer" line="三步走完，声音就立住了。" />
          </div>
          <div className={styles.guideMain}>
          <h3>角色工坊怎么用</h3>
          <p className={styles.guideLead}>
            把脑中的角色声音定下来，再用来试聊和写对白——不是普通聊天机器人。
          </p>
          <div className={styles.guideSteps}>
            <article>
              <strong>1. 定声音</strong>
              <span>
                生成三组对白，选最像的入库。请切换多个场景（被误解、别扭关心、面对权威等），
                单场景语料会片面。也可用长场次 / 采访加厚。
              </span>
            </article>
            <article>
              <strong>2. 出思维包</strong>
              <span>
                门槛任选其一：短正例≥6、不同场景≥5、长场次≥2、或角色台词约≥800字。
                够了再合成；也可导出给女娲加深后导入。
              </span>
            </article>
            <article>
              <strong>3. 试聊排练</strong>
              <span>有思维包后，与角色对话，或让两个角色互聊验收口吻。</span>
            </article>
          </div>
          <label className={styles.guideCheck}>
            <input
              type="checkbox"
              checked={dontShowGuideAgain}
              onChange={(e) => setDontShowGuideAgain(e.target.checked)}
            />
            下次不再出现
          </label>
          <div className={styles.guideActions}>
            <button
              type="button"
              className={styles.primary}
              onClick={() => {
                dismissGuide();
                goStep("shape");
              }}
            >
              开始塑形
            </button>
            <button type="button" onClick={dismissGuide}>
              知道了
            </button>
          </div>
          </div>
        </div>
      </div>
    );
  }

  if (!characters.length) {
    return (
      <section className={styles.page}>
        <header className={styles.hero}>
          <div className={styles.heroBanner} aria-hidden />
          <div className={styles.heroCopy}>
            <p className={styles.heroIdx}>档案室 · FILE</p>
            <h2>角色工坊</h2>
            <p className={styles.heroValue}>定声音 → 思维包 → 试聊</p>
          </div>
        </header>
        <div className={styles.emptyStage}>
          <img
            className={styles.emptyArt}
            src="/workshop/workshop-empty.png"
            alt=""
          />
          <p>还没有角色</p>
          <span>先在「设定 → 角色卡」添加角色，再回来塑形与试聊。</span>
        </div>
      </section>
    );
  }

  return (
    <section className={styles.page}>
      {renderGuide()}
      <header className={styles.hero}>
        <div className={styles.heroBanner} aria-hidden />
        <div className={styles.heroCopy}>
          <p className={styles.heroIdx}>档案室 · FILE</p>
          <h2>角色工坊</h2>
          <p className={styles.heroValue}>
            定声音 → 思维包 → 试聊 / 写对白
          </p>
        </div>
        <div className={styles.heroMeta}>
          <button
            type="button"
            className={styles.railToggle}
            aria-expanded={railOpen}
            onClick={() => setRailOpen((v) => !v)}
          >
            {railOpen ? "收起名单" : "打开名单"}
          </button>
          {!showGuide && (
            <button
              type="button"
              className={styles.ghostLink}
              onClick={() => {
                setDontShowGuideAgain(false);
                setShowGuide(true);
              }}
            >
              查看引导
            </button>
          )}
        </div>
      </header>

      {renderProgress()}

      <div className={styles.layout}>
        {railOpen && (
          <button
            type="button"
            className={styles.railScrim}
            aria-label="关闭角色名单"
            onClick={() => setRailOpen(false)}
          />
        )}
        <aside
          className={`${styles.rail} ${railOpen ? styles.railDrawerOpen : ""}`}
          id="workshop-rail"
        >
          <div className={styles.railHead}>
            <div>
              <p className={styles.railKicker}>CAST</p>
              <p className={styles.railLabel}>角色名单</p>
            </div>
            <button
              type="button"
              className={styles.railClose}
              onClick={() => setRailOpen(false)}
            >
              关闭
            </button>
          </div>
          <ul className={styles.charList}>
            {characters.map((c, i) => {
              const n = c.voiceCorpus?.length || 0;
              const active = c.id === character?.id;
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    className={active ? styles.charActive : styles.charBtn}
                    onClick={() => {
                      setCharId(c.id);
                      setRailOpen(false);
                    }}
                  >
                    <span className={styles.charIdx} aria-hidden>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span
                      className={styles.swatch}
                      style={{ background: c.color || "#888" }}
                    />
                    <span className={styles.charName}>{c.displayName}</span>
                    <span className={styles.charStat}>
                      {n}
                      {c.voiceMind ? " · 包" : ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {character ? (
            <div className={styles.dossierCard}>
              <div className={styles.dossierMark} aria-hidden>
                档
              </div>
              <div className={styles.dossierHead}>
                <p className={styles.dossierIdx}>
                  FILE{" "}
                  {String(
                    Math.max(
                      1,
                      characters.findIndex((c) => c.id === character.id) + 1,
                    ),
                  ).padStart(2, "0")}
                </p>
                <h3
                  className={styles.dossierName}
                  style={{ color: character.color || undefined }}
                >
                  {character.displayName}
                </h3>
                <p className={styles.dossierMeta}>
                  {sampleCount} 正例 · 覆盖 {coverage} 场景
                  {hasMindPack ? " · 已有思维包" : " · 尚无思维包"}
                  {ready ? " · 可合成" : ""}
                </p>
              </div>
              <dl className={styles.dossierGrid}>
                <div>
                  <dt>短正例</dt>
                  <dd>{shortCount}</dd>
                </div>
                <div>
                  <dt>长场次</dt>
                  <dd>{sceneCount}</dd>
                </div>
                <div>
                  <dt>采访</dt>
                  <dd>{interviewCount}</dd>
                </div>
                <div>
                  <dt>字量</dt>
                  <dd>{volumeChars}</dd>
                </div>
                <div>
                  <dt>场景</dt>
                  <dd>{coverage}</dd>
                </div>
                <div>
                  <dt>可合成</dt>
                  <dd>{ready ? "是" : "否"}</dd>
                </div>
                <div>
                  <dt>思维包</dt>
                  <dd>{hasMindPack ? "有" : "无"}</dd>
                </div>
              </dl>
              <div className={styles.dossierSeed}>
                <p>
                  <em>语气</em>
                  {character.voice || "（空）"}
                </p>
                <p>
                  <em>简介</em>
                  {character.bio || "（空）"}
                </p>
              </div>
            </div>
          ) : null}
        </aside>

        <div className={styles.stage} ref={zonePanelRef}>
          <div className={styles.zoneTabs}>
            {(
              [
                ["shape", "塑形"],
                ["pack", "思维包"],
                ["chat", "对话"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={zone === id ? styles.zoneTabOn : styles.zoneTab}
                onClick={() => goStep(id)}
              >
                {label}
              </button>
            ))}
          </div>

          {error && <p className={styles.error}>{error}</p>}

          {zone === "shape" && renderShapeZone()}
          {zone === "pack" && renderPackZone()}
          {zone === "chat" && renderChatZone()}
        </div>
      </div>
    </section>
  );
}
