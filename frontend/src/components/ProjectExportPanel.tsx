import { EmptyStage } from "./EmptyStage";
import { mascotLine } from "../lib/mascotCopy";
import styles from "./StudioApp.module.css";

type Props = {
  rpyPreview: string | null;
  rpyStale: boolean;
  onGenerateRpy: () => void;
  onDownloadRpy: () => void;
  onDownloadJson: () => void;
  onDownloadMarkdown: () => void;
  onDownloadDocx: () => void;
  onDownloadBundle: () => void;
  bundleBusy: boolean;
};

/**
 * 项目 → 导出 sub-tab: generate/download .rpy, download project JSON,
 * submission exports (Markdown / Word), download full Ren'Py project zip.
 * Pure presentational — export/status logic stays in StudioApp.
 */
export function ProjectExportPanel({
  rpyPreview,
  rpyStale,
  onGenerateRpy,
  onDownloadRpy,
  onDownloadJson,
  onDownloadMarkdown,
  onDownloadDocx,
  onDownloadBundle,
  bundleBusy,
}: Props) {
  return (
    <>
      <div className={styles.toolbar}>
        <span>
          先根据当前剧本生成 .rpy 预览；投稿可直接下载 Markdown / Word 稿，工程
          JSON 随时导出；需要可运行工程时下载 Ren'Py 项目包（zip）。
        </span>
        <div className={styles.aiQuick}>
          <button type="button" className={styles.primary} onClick={onGenerateRpy}>
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
          <button type="button" onClick={onDownloadMarkdown} title="投稿用 Markdown 稿">
            下载 Markdown
          </button>
          <button type="button" onClick={onDownloadDocx} title="投稿用 Word 稿（.docx）">
            下载 Word
          </button>
          <button type="button" onClick={onDownloadJson}>
            下载工程 .json
          </button>
          <button
            type="button"
            disabled={bundleBusy}
            onClick={onDownloadBundle}
            title="下载完整 Ren'Py 项目骨架（script/options/gui/README 打包为 zip）"
          >
            {bundleBusy ? "打包中…" : "下载 Ren'Py 项目包"}
          </button>
        </div>
      </div>
      {rpyStale && rpyPreview && (
        <p className={styles.hint}>
          剧本已修改，预览已过期 — 请重新点击「生成 .rpy」。
        </p>
      )}
      {!rpyPreview ? (
        <EmptyStage stamp="EXP" title="尚无导出预览" line={mascotLine("emptyExport")}>
          <button type="button" className={styles.primary} onClick={onGenerateRpy}>
            生成 .rpy
          </button>
        </EmptyStage>
      ) : (
        <pre className={styles.pre}>{rpyPreview}</pre>
      )}
    </>
  );
}
