import { EmptyStage } from "./EmptyStage";
import { mascotLine } from "../lib/mascotCopy";
import styles from "./StudioApp.module.css";

type Props = {
  rpyPreview: string | null;
  rpyStale: boolean;
  onGenerateRpy: () => void;
  onDownloadRpy: () => void;
  onDownloadJson: () => void;
};

/**
 * 项目 → 导出 sub-tab: generate/download .rpy, download project JSON.
 * Pure presentational — export/status logic stays in StudioApp.
 */
export function ProjectExportPanel({
  rpyPreview,
  rpyStale,
  onGenerateRpy,
  onDownloadRpy,
  onDownloadJson,
}: Props) {
  return (
    <>
      <div className={styles.toolbar}>
        <span>
          先根据当前剧本生成 .rpy 预览，确认无误后再下载；工程 JSON 可随时导出。
        </span>
        <div className={styles.aiQuick}>
          <button
            type="button"
            className={styles.primary}
            onClick={onGenerateRpy}
          >
            生成 .rpy
          </button>
          <button
            type="button"
            disabled={!rpyPreview || rpyStale}
            onClick={onDownloadRpy}
            title={
              !rpyPreview
                ? "请先生成"
                : rpyStale
                  ? "剧本已改动，请重新生成"
                  : "下载预览中的 .rpy"
            }
          >
            下载 .rpy
          </button>
          <button type="button" onClick={onDownloadJson}>
            下载工程 .json
          </button>
        </div>
      </div>
      {rpyStale && rpyPreview && (
        <p className={styles.hint}>
          剧本已修改，预览已过期 — 请重新点击「生成 .rpy」。
        </p>
      )}
      {!rpyPreview ? (
        <EmptyStage
          stamp="EXP"
          title="尚无导出预览"
          line={mascotLine("emptyExport")}
        >
          <button
            type="button"
            className={styles.primary}
            onClick={onGenerateRpy}
          >
            生成 .rpy
          </button>
        </EmptyStage>
      ) : (
        <pre className={styles.pre}>{rpyPreview}</pre>
      )}
    </>
  );
}
