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
          按你的目的选：投稿 / 交稿 → 「下载 Word」或「下载 Markdown」；想在电脑上运行试玩
          → 「下载 Ren'Py 项目包（zip）」（Ren'Py 是免费的文字冒险游戏制作软件，用它打开即可运行）。
          「生成 .rpy / 下载 .rpy」是给想在 Ren'Py 里继续改脚本的进阶用法；「下载工程 .json」是整份作品的备份文件。
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
          <button type="button" onClick={onDownloadJson} title="整份作品的备份文件，以后可导入恢复">
            下载工程备份 (.json)
          </button>
          <button
            type="button"
            disabled={bundleBusy}
            onClick={onDownloadBundle}
            title="下载一个 zip，内含可直接运行的完整工程文件，用免费的 Ren'Py 引擎打开即可试玩"
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
