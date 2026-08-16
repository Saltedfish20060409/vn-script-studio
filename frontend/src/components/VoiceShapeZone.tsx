import type {
  VoiceAxisTag,
  VoiceScenario,
  VoiceVariant,
} from "../api/client";
import type { VoiceCorpusSample } from "../types/vn";
import { VoiceAxisTagPanel } from "./VoiceAxisTagPanel";
import { VoiceCorpusDrawer, type ExtractRow } from "./VoiceCorpusDrawer";
import { VoiceInterviewPanel } from "./VoiceInterviewPanel";
import { VoicePreferenceCards } from "./VoicePreferenceCards";
import { VoiceReadinessBanner, type ReadinessInfo } from "./VoiceReadinessBanner";
import { VoiceSceneEditor } from "./VoiceSceneEditor";
import {
  VoiceScenarioControls,
  ensureCustomScenario,
  type ShapeMode,
} from "./VoiceScenarioControls";
import type { PendingAccept } from "./VoiceWhyPanel";
import styles from "./CharacterWorkshop.module.css";

type Props = {
  shapeMode: ShapeMode;
  scenarios: VoiceScenario[];
  scenarioId: string;
  scenarioPrompt: string;
  customScenarioLabel: string;
  constraints: string;
  busy: string;
  hasCharacter: boolean;
  resolvedLongSuitable: boolean;
  variants: VoiceVariant[];
  confirmedAxes: string[];
  uniqueCount: number;
  axisTags: VoiceAxisTag[];
  selectedTagIds: string[];
  sampleCount: number;
  ready: boolean;
  readinessInfo: ReadinessInfo;
  readinessNarrow: string;
  unlikeOpen: boolean;
  unlikeAxis: string;
  unlikeCustomAxis: string;
  unlikeText: string;
  pendingAccept: PendingAccept | null;
  whyOpen: boolean;
  whyChips: string[];
  whyCustom: string;
  sceneText: string;
  interviewQuestion: string;
  genQuestion: string | undefined;
  interviewManual: string;
  manualText: string;
  drawerOpen: boolean;
  corpus: VoiceCorpusSample[];
  extractRows: ExtractRow[];
  onModeChange: (mode: ShapeMode) => void;
  onScenarioSelect: (id: string) => void;
  onScenarioPromptChange: (value: string) => void;
  onCustomLabelChange: (value: string) => void;
  onConstraintsChange: (value: string) => void;
  onGenerate: () => void;
  onRejectAll: () => void;
  onSameSceneRetry: () => void;
  onAcceptVariant: (
    variant: VoiceVariant,
    index: number,
    source: "preference" | "interview"
  ) => void;
  onUnlikeAxisSelect: (axis: string) => void;
  onUnlikeCustomAxisChange: (value: string) => void;
  onUnlikeTextChange: (value: string) => void;
  onAcceptUnlike: () => void;
  onDiscardUnlike: () => void;
  onToggleWhyChip: (chip: string) => void;
  onWhyCustomChange: (value: string) => void;
  onWhyConfirm: (note: string) => void;
  onWhySkip: () => void;
  onWhyCancel: () => void;
  onSceneTextChange: (value: string) => void;
  onAcceptScene: () => void;
  onInterviewQuestionChange: (value: string) => void;
  onInterviewManualChange: (value: string) => void;
  onManualTextChange: (value: string) => void;
  onAcceptManual: (source: "manual" | "interview") => void;
  onToggleAxisTag: (id: string) => void;
  onClearTags: () => void;
  onDrawerToggle: () => void;
  onExtract: () => void;
  onDeleteSample: (id: string) => void;
  onToggleRow: (index: number, checked: boolean) => void;
  onAcceptExtract: () => void;
};

function generateLabel(shapeMode: ShapeMode): string {
  switch (shapeMode) {
    case "scene":
      return "生成长场次";
    case "interview":
      return "生成三组回答";
    default:
      return "生成三组";
  }
}

export function VoiceShapeZone({
  shapeMode,
  scenarios,
  scenarioId,
  scenarioPrompt,
  customScenarioLabel,
  constraints,
  busy,
  hasCharacter,
  resolvedLongSuitable,
  variants,
  confirmedAxes,
  uniqueCount,
  axisTags,
  selectedTagIds,
  sampleCount,
  ready,
  readinessInfo,
  readinessNarrow,
  unlikeOpen,
  unlikeAxis,
  unlikeCustomAxis,
  unlikeText,
  pendingAccept,
  whyOpen,
  whyChips,
  whyCustom,
  sceneText,
  interviewQuestion,
  genQuestion,
  interviewManual,
  manualText,
  drawerOpen,
  corpus,
  extractRows,
  onModeChange,
  onScenarioSelect,
  onScenarioPromptChange,
  onCustomLabelChange,
  onConstraintsChange,
  onGenerate,
  onRejectAll,
  onSameSceneRetry,
  onAcceptVariant,
  onUnlikeAxisSelect,
  onUnlikeCustomAxisChange,
  onUnlikeTextChange,
  onAcceptUnlike,
  onDiscardUnlike,
  onToggleWhyChip,
  onWhyCustomChange,
  onWhyConfirm,
  onWhySkip,
  onWhyCancel,
  onSceneTextChange,
  onAcceptScene,
  onInterviewQuestionChange,
  onInterviewManualChange,
  onManualTextChange,
  onAcceptManual,
  onToggleAxisTag,
  onClearTags,
  onDrawerToggle,
  onExtract,
  onDeleteSample,
  onToggleRow,
  onAcceptExtract,
}: Props) {
  function renderScenarioControls(showGenerate = true) {
    const list = ensureCustomScenario(
      scenarios.length
        ? scenarios
        : [{ id: "misunderstood", label: "被误解时", prompt: "" }]
    );
    return (
      <VoiceScenarioControls
        scenarios={list}
        shapeMode={shapeMode}
        scenarioId={scenarioId}
        scenarioPrompt={scenarioPrompt}
        customScenarioLabel={customScenarioLabel}
        constraints={constraints}
        busy={busy}
        hasCharacter={hasCharacter}
        showGenerate={showGenerate}
        generateLabel={generateLabel(shapeMode)}
        resolvedLongSuitable={resolvedLongSuitable}
        variantCount={variants.length}
        selectedTagCount={selectedTagIds.length}
        sampleCount={sampleCount}
        onScenarioSelect={onScenarioSelect}
        onScenarioPromptChange={onScenarioPromptChange}
        onCustomLabelChange={onCustomLabelChange}
        onConstraintsChange={onConstraintsChange}
        onGenerate={onGenerate}
        onRejectAll={onRejectAll}
        onSameSceneRetry={onSameSceneRetry}
      />
    );
  }

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
            onClick={() => onModeChange(id)}
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
          {uniqueCount > 0 && (
            <>
              {" "}
              已覆盖 <em>{uniqueCount}</em> 类场景。
            </>
          )}
        </p>
      )}

      {(shapeMode === "preference" || shapeMode === "interview") &&
        axisTags.length > 0 && (
        <VoiceAxisTagPanel
          tags={axisTags}
          selectedIds={selectedTagIds}
          onToggle={onToggleAxisTag}
          onClear={onClearTags}
        />
      )}

      {shapeMode === "preference" && sampleCount > 0 && !ready && (
        <div className={styles.readyBannerCompact}>
          <VoiceReadinessBanner
            info={readinessInfo}
            narrow={readinessNarrow}
            compact
          />
        </div>
      )}

      {shapeMode === "interview" && (
        <label className={`${styles.field} ${styles.grow}`}>
          采访问题（可留空由系统出题）
          <input
            value={interviewQuestion}
            onChange={(e) => onInterviewQuestionChange(e.target.value)}
            placeholder="例如：你最怕别人发现你哪一点？"
          />
        </label>
      )}

      {shapeMode === "preference" && (
        <VoicePreferenceCards
          variants={variants}
          busy={busy}
          hasCharacter={hasCharacter}
          unlikeOpen={unlikeOpen}
          unlikeAxis={unlikeAxis}
          unlikeCustomAxis={unlikeCustomAxis}
          unlikeText={unlikeText}
          pendingAccept={pendingAccept}
          whyOpen={whyOpen}
          whyChips={whyChips}
          whyCustom={whyCustom}
          onGenerate={onGenerate}
          onAcceptVariant={(v, i) =>
            void onAcceptVariant(v, i, "preference")
          }
          onUnlikeAxisSelect={onUnlikeAxisSelect}
          onUnlikeCustomAxisChange={onUnlikeCustomAxisChange}
          onUnlikeTextChange={onUnlikeTextChange}
          onAcceptUnlike={onAcceptUnlike}
          onDiscardUnlike={onDiscardUnlike}
          onToggleWhyChip={onToggleWhyChip}
          onWhyCustomChange={onWhyCustomChange}
          onWhyConfirm={onWhyConfirm}
          onWhySkip={onWhySkip}
          onWhyCancel={onWhyCancel}
        />
      )}

      {shapeMode === "scene" && (
        <VoiceSceneEditor
          busy={busy}
          sceneText={sceneText}
          hasCharacter={hasCharacter}
          onTextChange={onSceneTextChange}
          onAccept={onAcceptScene}
          onRegenerate={onGenerate}
          onGenerate={onGenerate}
        />
      )}

      {shapeMode === "interview" && (
        <VoiceInterviewPanel
          question={interviewQuestion}
          genQuestion={genQuestion}
          variants={variants}
          busy={busy}
          hasCharacter={hasCharacter}
          interviewManual={interviewManual}
          pendingAccept={pendingAccept}
          whyOpen={whyOpen}
          whyChips={whyChips}
          whyCustom={whyCustom}
          onGenerate={onGenerate}
          onAcceptVariant={(v, i) =>
            void onAcceptVariant(v, i, "interview")
          }
          onManualChange={onInterviewManualChange}
          onAcceptManual={() => onAcceptManual("interview")}
          onToggleWhyChip={onToggleWhyChip}
          onWhyCustomChange={onWhyCustomChange}
          onWhyConfirm={onWhyConfirm}
          onWhySkip={onWhySkip}
          onWhyCancel={onWhyCancel}
        />
      )}

      {shapeMode === "manual" && (
        <div className={styles.manualBox}>
          <p className={styles.manualHint}>
            每行一句，或「角色：台词」格式；直接作为金句正例入库
          </p>
          {renderScenarioControls(false)}
          <textarea
            value={manualText}
            onChange={(e) => onManualTextChange(e.target.value)}
            placeholder={"短句一\n角色：短句二"}
          />
          <button
            type="button"
            className={styles.primary}
            disabled={!!busy || !manualText.trim()}
            onClick={() => onAcceptManual("manual")}
          >
            {busy === "accept-manual" ? "入库中…" : "金句入库"}
          </button>
        </div>
      )}

      <VoiceCorpusDrawer
        open={drawerOpen}
        sampleCount={sampleCount}
        busy={busy}
        corpus={corpus}
        extractRows={extractRows}
        onToggle={onDrawerToggle}
        onExtract={onExtract}
        onDelete={onDeleteSample}
        onToggleRow={onToggleRow}
        onAcceptExtract={onAcceptExtract}
      />
    </>
  );
}
