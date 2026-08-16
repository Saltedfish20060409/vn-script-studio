import { VoiceReadinessBanner, type ReadinessInfo } from "./VoiceReadinessBanner";
import styles from "./CharacterWorkshop.module.css";

type Props = {
  busy: string;
  sampleCount: number;
  ready: boolean;
  showImport: boolean;
  importMd: string;
  mind: string;
  readiness: ReadinessInfo;
  narrow: string;
  onSynthesize: (force: boolean) => void;
  onExport: () => void;
  onToggleImport: () => void;
  onImportMdChange: (value: string) => void;
  onImportMind: () => void;
};

export function VoicePackZone({
  busy,
  sampleCount,
  ready,
  showImport,
  importMd,
  mind,
  readiness,
  narrow,
  onSynthesize,
  onExport,
  onToggleImport,
  onImportMdChange,
  onImportMind,
}: Props) {
  return (
    <div className={styles.packZone}>
      <p className={styles.muted}>
        思维包由正例语料蒸馏而来，写剧本与对话时 Agent 会参照其中的口吻规则。
      </p>
      <VoiceReadinessBanner info={readiness} narrow={narrow} />
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          disabled={!!busy || sampleCount < 1 || (!ready && busy !== "synth")}
          title={!ready ? "未达推荐门槛时可点「强制合成」，但质量可能偏差" : undefined}
          onClick={() => onSynthesize(false)}
        >
          {busy === "synth" ? "合成中…" : "合成思维包"}
        </button>
        <button
          type="button"
          disabled={!!busy || sampleCount < 1}
          onClick={() => onSynthesize(true)}
          title="样本不足时也可强制，建议先换场景多攒几条"
        >
          强制合成
        </button>
        <button type="button" disabled={!!busy} onClick={onExport}>
          导出女娲包
        </button>
        <button type="button" disabled={!!busy} onClick={onToggleImport}>
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
            onChange={(e) => onImportMdChange(e.target.value)}
            placeholder="粘贴女娲蒸馏后的 SKILL.md / 思维包 markdown…"
          />
          <button
            type="button"
            className={styles.primary}
            disabled={!!busy}
            onClick={onImportMind}
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
