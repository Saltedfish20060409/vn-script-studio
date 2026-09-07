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
import { VoiceChatZone, type ChatMode, type ChatMsg } from "./VoiceChatZone";
import { VoiceGuideOverlay } from "./VoiceGuideOverlay";
import { VoicePackZone } from "./VoicePackZone";
import { VoiceProgressRail } from "./VoiceProgressRail";
import { VoiceRail } from "./VoiceRail";
import { ensureCustomScenario, promptSlug, type ShapeMode } from "../lib/voiceScenarios";
import { VoiceShapeZone } from "./VoiceShapeZone";
import { VoiceWorkshopEmpty } from "./VoiceWorkshopEmpty";
import { VoiceWorkshopHero } from "./VoiceWorkshopHero";
import type { PendingAccept } from "./VoiceWhyPanel";
import styles from "./CharacterWorkshop.module.css";

type Props = {
  project: VnProject;
  onProjectChange: (p: VnProject) => void;
};

type Zone = "shape" | "pack" | "chat";

type GenMeta = {
  scenarioId: string;
  scenarioLabel: string;
  scenarioPrompt?: string;
  question?: string;
};

const GUIDE_STORAGE_KEY = "vnss-workshop-guide-v1";

function readGuideDismissed(): boolean {
  try {
    return localStorage.getItem(GUIDE_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function linesToText(lines: Array<{ speaker: string; text: string }>) {
  return lines
    .map((ln) => {
      const sp =
        ln.speaker === "self" ? "角色" : ln.speaker === "other" ? "对方" : ln.speaker;
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

const GENERIC_CUSTOM_LABELS = new Set(["", "自定义", "自定义…", "custom"]);

/** Align with backend normalize_scenario_key for coverage display */
function scenarioCoverageKey(s: VoiceCorpusSample): string {
  const sid = (s.scenario || "").trim();
  let label = (s.scenarioLabel || "").trim();
  if (label.startsWith("长场次·"))
    label = label.slice("长场次·".length).trim() || label;
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
  const { sampleCount, coverage, volumeChars, sceneCount, interviewCount, ready } =
    opts;
  const paths = [
    `短对白示例 ${sampleCount}/${READY_TARGETS.samples}`,
    `不同场景 ${coverage}/${READY_TARGETS.coverage}`,
    `角色台词约 ${volumeChars}/${READY_TARGETS.volume} 字`,
    `长场次 ${sceneCount}/${READY_TARGETS.scenes}`,
    `采访 ${interviewCount}/${READY_TARGETS.interviews}（且字量≥${READY_TARGETS.interviewVolume}）`,
  ];
  if (ready) {
    return {
      ready: true,
      paths,
      nextHint: "素材够了，可以到「思维包」生成角色的口吻规则了。",
    };
  }
  const remain: string[] = [];
  if (sampleCount < READY_TARGETS.samples) {
    remain.push(`再收集 ${READY_TARGETS.samples - sampleCount} 条短对白示例`);
  }
  if (coverage < READY_TARGETS.coverage) {
    remain.push(`再换 ${READY_TARGETS.coverage - coverage} 类不同场景做三选一`);
  }
  if (volumeChars < READY_TARGETS.volume) {
    remain.push(
      `或用长场次把台词堆到约 ${READY_TARGETS.volume} 字（还差约 ${Math.max(0, READY_TARGETS.volume - volumeChars)} 字）`
    );
  }
  if (sceneCount < READY_TARGETS.scenes) {
    remain.push(`或再存 ${READY_TARGETS.scenes - sceneCount} 段长场次示例`);
  }
  return {
    ready: false,
    paths,
    nextHint: `任选一条路径凑够即可合成：${remain.slice(0, 3).join("；")}。`,
  };
}

export function CharacterWorkshop({ project, onProjectChange }: Props) {
  // Stable reference: `|| []` alone would create a new array every render,
  // churning useMemo/useEffect deps below.
  const characters = useMemo(() => project.characters || [], [project.characters]);
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
  const [pendingAccept, setPendingAccept] = useState<PendingAccept | null>(null);
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
      characters.filter((c) => c.id !== character?.id && (c.voiceMind || "").trim()),
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
    const isCustom = scenarioId === "custom" || scenarioId.startsWith("custom:");
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
    const label = named && !GENERIC_CUSTOM_LABELS.has(named) ? named : slug || "未命名";
    return {
      id: `custom:${label}`,
      label,
      prompt: scenarioPrompt || "",
      isCustom: true,
      longSuitable: true,
    };
  }, [scenarioId, customScenarioLabel, selectedScenario, scenarioPrompt]);

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
    const extra = constraintOverride !== undefined ? constraintOverride : constraints;
    try {
      const kind = shapeMode === "manual" ? "preference" : shapeMode;
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
      setError(e instanceof Error ? e.message : "保存示例失败");
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
      setError(e instanceof Error ? e.message : "保存示例失败");
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
        scenario_id: source === "interview" ? "interview" : resolvedScenario.id,
        scenario_label:
          source === "interview"
            ? `采访·${(genMeta?.question || interviewQuestion || "手动").slice(0, 20)}`
            : resolvedScenario.label,
        scenario_prompt: source === "interview" ? undefined : resolvedScenario.prompt,
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
      setError(e instanceof Error ? e.message : "保存示例失败");
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
      setError(e instanceof Error ? e.message : "保存示例失败");
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
      content: m.speakerName ? `${m.speakerName}：${m.content}` : m.content,
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
          action: ln.action || undefined,
          mood: ln.mood || undefined,
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
          action: res.action || undefined,
          mood: res.mood || undefined,
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

  const uniqueCount = uniqueScenarios(corpus).length;
  const readinessInfo = readinessPaths({
    sampleCount,
    coverage,
    volumeChars,
    sceneCount,
    interviewCount,
    ready,
  });
  const readinessNarrow = (() => {
    const unique = uniqueScenarios(corpus);
    if (sampleCount >= 2 && unique.length <= 1) {
      return "目前语料几乎只来自同一场景，形象容易片面。请换几个压力场景再做三选一（被误解 / 别扭关心 / 面对权威等）。";
    }
    if (unique.length > 0 && unique.length < 3 && sampleCount >= 3) {
      return `已覆盖 ${unique.length} 类场景。建议至少再换 2～3 个不同场景，对白感觉会稳很多。`;
    }
    return "";
  })();

  function handleScenarioSelect(id: string) {
    setScenarioId(id);
    const list = ensureCustomScenario(
      scenarios.length
        ? scenarios
        : [{ id: "misunderstood", label: "被误解时", prompt: "" }]
    );
    const sc = list.find((s) => s.id === id);
    if (id === "custom") {
      if (!scenarioPrompt.trim()) setScenarioPrompt("");
    } else if (sc) {
      setScenarioPrompt(sc.prompt);
    }
  }

  function handleSameSceneRetry() {
    const next = constraints.includes("对齐已选正例")
      ? constraints
      : [constraints, "必须对齐已选正例与思维包；禁止换人设"]
          .filter(Boolean)
          .join("；");
    setConstraints(next);
    void onGenerate(next);
  }

  function handleUnlikeAxisSelect(axis: string) {
    setUnlikeAxis(axis);
    setUnlikeCustomAxis("");
  }

  function handleDiscardUnlike() {
    setUnlikeOpen(false);
    resetGen();
    if (!constraints) setConstraints("再短一点；少卖萌；少书面语");
  }

  function handleWhyCancel() {
    setWhyOpen(false);
    setPendingAccept(null);
    setWhyChips([]);
    setWhyCustom("");
  }

  function handleToggleRow(index: number, checked: boolean) {
    setExtractRows((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], selected: checked };
      return next;
    });
  }

  function handleToggleDrawer() {
    setDrawerOpen((v) => !v);
  }

  function handleClearChat() {
    setChatMessages([]);
    setLastReplyLines([]);
  }

  function handleSelectChar(id: string) {
    setCharId(id);
    setRailOpen(false);
  }

  function handleRailToggle() {
    setRailOpen((v) => !v);
  }

  function handleShowGuide() {
    setDontShowGuideAgain(false);
    setShowGuide(true);
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
      const scroller = el.closest(
        "[data-workshop-scroll], main, .shell"
      ) as HTMLElement | null;
      if (
        scroller &&
        scroller !== el &&
        scroller.scrollHeight > scroller.clientHeight
      ) {
        const top =
          el.getBoundingClientRect().top -
          scroller.getBoundingClientRect().top +
          scroller.scrollTop -
          12;
        scroller.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      }
    }, 40);
  }

  if (!characters.length) {
    return <VoiceWorkshopEmpty />;
  }

  return (
    <section className={styles.page}>
      {showGuide && (
        <VoiceGuideOverlay
          dontShowGuideAgain={dontShowGuideAgain}
          onToggleCheck={setDontShowGuideAgain}
          onDismiss={dismissGuide}
          onStart={() => {
            dismissGuide();
            goStep("shape");
          }}
        />
      )}
      <VoiceWorkshopHero
        value="定口吻 → 合成思维包 → 试聊 / 写对白"
        railOpen={railOpen}
        onToggleRail={handleRailToggle}
        showGuide={showGuide}
        onShowGuide={handleShowGuide}
      />
      <div className={styles.castBar}>
        <div>
          <p className={styles.castKicker}>当前角色</p>
          <p className={styles.castName}>
            {character?.displayName || "未选择"}
          </p>
        </div>
        <div className={styles.castActions}>
          <button
            type="button"
            className={styles.railToggle}
            aria-expanded={railOpen}
            onClick={handleRailToggle}
          >
            {railOpen ? "收起名单" : "换角色"}
          </button>
          {!showGuide ? (
            <button type="button" className={styles.ghostLink} onClick={handleShowGuide}>
              查看引导
            </button>
          ) : null}
        </div>
      </div>

      <VoiceProgressRail
        sampleCount={sampleCount}
        uniqueCount={uniqueCount}
        hasMindPack={hasMindPack}
        ready={ready}
        nextHint={readinessInfo.nextHint}
        onStep={goStep}
      />

      <div className={styles.layout}>
        {railOpen && (
          <button
            type="button"
            className={styles.railScrim}
            aria-label="关闭角色名单"
            onClick={() => setRailOpen(false)}
          />
        )}
        <VoiceRail
          railOpen={railOpen}
          characters={characters}
          character={character}
          stats={{
            sampleCount,
            coverage,
            hasMindPack,
            ready,
            shortCount,
            sceneCount,
            interviewCount,
            volumeChars,
          }}
          onSelectChar={handleSelectChar}
          onClose={() => setRailOpen(false)}
        />

        <div className={styles.stage} ref={zonePanelRef}>
          <div className={styles.zoneTabs}>
            {(
              [
                ["shape", "定口吻"],
                ["pack", "思维包"],
                ["chat", "试聊"],
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

          {zone === "shape" && (
            <VoiceShapeZone
              shapeMode={shapeMode}
              scenarios={scenarios}
              scenarioId={scenarioId}
              scenarioPrompt={scenarioPrompt}
              customScenarioLabel={customScenarioLabel}
              constraints={constraints}
              busy={busy}
              hasCharacter={!!character}
              resolvedLongSuitable={!!resolvedScenario.longSuitable}
              variants={variants}
              confirmedAxes={confirmedAxes}
              uniqueCount={uniqueCount}
              axisTags={axisTags}
              selectedTagIds={selectedTagIds}
              sampleCount={sampleCount}
              ready={ready}
              readinessInfo={readinessInfo}
              readinessNarrow={readinessNarrow}
              unlikeOpen={unlikeOpen}
              unlikeAxis={unlikeAxis}
              unlikeCustomAxis={unlikeCustomAxis}
              unlikeText={unlikeText}
              pendingAccept={pendingAccept}
              whyOpen={whyOpen}
              whyChips={whyChips}
              whyCustom={whyCustom}
              sceneText={sceneText}
              interviewQuestion={interviewQuestion}
              genQuestion={genMeta?.question}
              interviewManual={interviewManual}
              manualText={manualText}
              drawerOpen={drawerOpen}
              corpus={corpus}
              extractRows={extractRows}
              onModeChange={(mode) => {
                setShapeMode(mode);
                resetGen();
              }}
              onScenarioSelect={handleScenarioSelect}
              onScenarioPromptChange={setScenarioPrompt}
              onCustomLabelChange={setCustomScenarioLabel}
              onConstraintsChange={setConstraints}
              onGenerate={() => void onGenerate()}
              onRejectAll={() => void onRejectAll()}
              onSameSceneRetry={handleSameSceneRetry}
              onAcceptVariant={(v, i, source) => void onAcceptVariant(v, i, source)}
              onUnlikeAxisSelect={handleUnlikeAxisSelect}
              onUnlikeCustomAxisChange={setUnlikeCustomAxis}
              onUnlikeTextChange={setUnlikeText}
              onAcceptUnlike={() => void onAcceptUnlike()}
              onDiscardUnlike={handleDiscardUnlike}
              onToggleWhyChip={toggleWhyChip}
              onWhyCustomChange={setWhyCustom}
              onWhyConfirm={(note) => void commitAcceptVariant(note)}
              onWhySkip={() => void commitAcceptVariant("")}
              onWhyCancel={handleWhyCancel}
              onSceneTextChange={setSceneText}
              onAcceptScene={() => void onAcceptScene()}
              onInterviewQuestionChange={setInterviewQuestion}
              onInterviewManualChange={setInterviewManual}
              onManualTextChange={setManualText}
              onAcceptManual={(source) => void onAcceptManual(source)}
              onToggleAxisTag={toggleAxisTag}
              onClearTags={() => setSelectedTagIds([])}
              onDrawerToggle={handleToggleDrawer}
              onExtract={() => void onExtract()}
              onDeleteSample={(id) => void onDeleteSample(id)}
              onToggleRow={handleToggleRow}
              onAcceptExtract={() => void onAcceptExtract()}
            />
          )}
          {zone === "pack" && (
            <VoicePackZone
              busy={busy}
              sampleCount={sampleCount}
              ready={ready}
              showImport={showImport}
              importMd={importMd}
              mind={mind}
              readiness={readinessInfo}
              narrow={readinessNarrow}
              onSynthesize={(force) => void onSynthesize(force)}
              onExport={() => void onExport()}
              onToggleImport={() => setShowImport((v) => !v)}
              onImportMdChange={setImportMd}
              onImportMind={() => void onImportMind()}
            />
          )}
          {zone === "chat" && (
            <VoiceChatZone
              hasMindPack={hasMindPack}
              chatMode={chatMode}
              partnerId={partnerId}
              partners={partnersWithMind}
              busy={busy}
              messages={chatMessages}
              chatInput={chatInput}
              canSave={lastReplyLines.length > 0}
              onModeChange={setChatMode}
              onPartnerChange={setPartnerId}
              onInputChange={setChatInput}
              onSend={() => void onSendChat()}
              onClear={handleClearChat}
              onSaveSample={() => void onSaveChatAsSample()}
              onGoPack={() => setZone("pack")}
            />
          )}
        </div>
      </div>
    </section>
  );
}
