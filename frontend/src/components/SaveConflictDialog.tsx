import { mascotLine } from "../lib/mascotCopy";
import styles from "./SaveConflictDialog.module.css";

export type SaveConflictChoice = "keep_local" | "take_server" | "download";

type Props = {
  open: boolean;
  localTitle?: string;
  serverUpdatedAt?: string;
  onChoose: (choice: SaveConflictChoice) => void;
};

/** Shown when PUT /projects hits 409 — never silent-overwrite without choice. */
export function SaveConflictDialog({
  open,
  localTitle,
  serverUpdatedAt,
  onChoose,
}: Props) {
  if (!open) return null;
  const when = serverUpdatedAt
    ? new Date(serverUpdatedAt).toLocaleString()
    : "未知时间";
  return (
    <div className={styles.backdrop} role="presentation">
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label="保存冲突"
      >
        <div className={styles.body}>
          <p className={styles.idx}>CONFLICT</p>
          <h3 className={styles.title}>你写的内容和云端对不上</h3>
          <p className={styles.line}>{mascotLine("confirmSoft")}</p>
          <p className={styles.msg}>
            「{localTitle || "当前工程"}」在服务器上已被更新过（{when}
            ），可能是另一台设备或另一位协作者保存的。你刚才没保存的修改还在，只是还没传上去。请选择怎么处理：
          </p>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              onClick={() => onChoose("keep_local")}
            >
              保留我这份（覆盖云端）
            </button>
            <button
              type="button"
              className={styles.ghost}
              onClick={() => onChoose("take_server")}
            >
              用云端那份（丢弃我这版）
            </button>
            <button
              type="button"
              className={styles.ghost}
              onClick={() => onChoose("download")}
            >
              先把我这版下载备份
            </button>
          </div>
          <p className={styles.hint}>
            「保留我这份」会用你刚写的内容盖掉云端（云端更新会丢）；「用云端那份」会丢弃你这次的改动（可先用「下载备份」留底）。下载的备份文件以后可以重新导入。
          </p>
        </div>
      </div>
    </div>
  );
}
