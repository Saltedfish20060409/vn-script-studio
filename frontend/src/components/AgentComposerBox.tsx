import type { RefObject } from "react";
import styles from "./AgentChat.module.css";

type Props = {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  compact?: boolean;
  busy: boolean;
  disabled: boolean;
  canSend: boolean;
  turnCount: number;
  attachBusy: boolean;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onPickFiles: (files: FileList | null) => void;
};

/**
 * 输入组合区：多行输入 + 附件 + 回合徽章 + 发送。
 * 纯受控展示——state 与 send/onPickFiles 逻辑留在 AgentChat。
 */
export function AgentComposerBox({
  value,
  onChange,
  onSend,
  compact,
  busy,
  disabled,
  canSend,
  turnCount,
  attachBusy,
  fileInputRef,
  onPickFiles,
}: Props) {
  return (
    <div className={styles.composer}>
      <textarea
        rows={compact ? 2 : 3}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="用平常话说：改这一章、再润、别动某某、整理关系…"
        disabled={disabled}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSend();
          }
        }}
      />
      <div className={styles.sendCluster}>
        <span className={styles.turnBadge} title="本对话用户发言次数">
          回合 {turnCount}
        </span>
        <input
          ref={fileInputRef}
          type="file"
          className={styles.fileInput}
          accept=".txt,.md,.markdown,.json,.csv,.docx,.rpy,text/plain,text/markdown,application/json"
          multiple
          disabled={disabled || attachBusy}
          onChange={(e) => onPickFiles(e.target.files)}
        />
        <button
          type="button"
          className={styles.attachBtn}
          disabled={disabled || attachBusy}
          title="上传参考资料（txt / md / docx / json / csv / rpy）"
          onClick={() => fileInputRef.current?.click()}
        >
          {attachBusy ? "…" : "附件"}
        </button>
        <button
          type="button"
          className={styles.sendBtn}
          disabled={disabled || !canSend}
          onClick={onSend}
        >
          {busy ? "…" : "发送"}
        </button>
      </div>
    </div>
  );
}
