import type { VoiceScenario } from "../api/client";
import styles from "./CharacterWorkshop.module.css";

export type ShapeMode = "preference" | "scene" | "interview" | "manual";

export function ensureCustomScenario(list: VoiceScenario[]): VoiceScenario[] {
  const has = list.some((s) => s.id === "custom");
  if (has) return list;
  return [
    ...list,
    { id: "custom", label: "自定义…", prompt: "", longSuitable: true },
  ];
}

export function promptSlug(prompt: string, maxLen = 16): string {
  return prompt.replace(/\s+/g, " ").trim().slice(0, maxLen);
}

type Props = {
  scenarios: VoiceScenario[];
  shapeMode: ShapeMode;
  scenarioId: string;
  scenarioPrompt: string;
  customScenarioLabel: string;
  constraints: string;
  busy: string;
  hasCharacter: boolean;
  showGenerate: boolean;
  generateLabel: string;
  resolvedLongSuitable: boolean;
  variantCount: number;
  selectedTagCount: number;
  sampleCount: number;
  onScenarioSelect: (id: string) => void;
  onScenarioPromptChange: (value: string) => void;
  onCustomLabelChange: (value: string) => void;
  onConstraintsChange: (value: string) => void;
  onGenerate: () => void;
  onRejectAll: () => void;
  onSameSceneRetry: () => void;
};

export function VoiceScenarioControls({
  scenarios,
  shapeMode,
  scenarioId,
  scenarioPrompt,
  customScenarioLabel,
  constraints,
  busy,
  hasCharacter,
  showGenerate,
  generateLabel,
  resolvedLongSuitable,
  variantCount,
  selectedTagCount,
  sampleCount,
  onScenarioSelect,
  onScenarioPromptChange,
  onCustomLabelChange,
  onConstraintsChange,
  onGenerate,
  onRejectAll,
  onSameSceneRetry,
}: Props) {
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
          onChange={(e) => onScenarioSelect(e.target.value)}
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
            onChange={(e) => onCustomLabelChange(e.target.value)}
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
          {resolvedLongSuitable
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
          onChange={(e) => onScenarioPromptChange(e.target.value)}
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
          onChange={(e) => onConstraintsChange(e.target.value)}
          placeholder="再短一点；禁止卖萌"
        />
      </label>
      {showGenerate && (
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primary}
            disabled={!!busy || !hasCharacter}
            onClick={() => onGenerate()}
          >
            {busy === "generating" ? "生成中…" : generateLabel}
          </button>
          {shapeMode === "preference" && variantCount > 0 && (
            <button
              type="button"
              disabled={!!busy}
              onClick={() => onRejectAll()}
            >
              都不像…
            </button>
          )}
          {shapeMode === "preference" && selectedTagCount > 0 && (
            <button
              type="button"
              disabled={!!busy || !hasCharacter}
              onClick={() => onGenerate()}
              title="按已勾标签重开三组"
            >
              按标签重开
            </button>
          )}
          {shapeMode === "preference" && sampleCount >= 1 && (
            <button
              type="button"
              disabled={!!busy}
              onClick={() => onSameSceneRetry()}
            >
              同场景试写
            </button>
          )}
        </div>
      )}
    </div>
  );
}
