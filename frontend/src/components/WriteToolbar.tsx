import { SpeechInputButton } from "./SpeechInputButton";
import styles from "./StudioApp.module.css";

type Props = {
  /** 语音插入正文；格式切换 / 查找 / 改稿已迁到顶栏「开始」「审阅」菜单 */
  onDictateInsert?: (text: string) => void;
};

/**
 * 稿纸旁的精简条：只留语音输入。
 * 正文/脚本、查找、生成脚本、改稿对照都在 StudioRibbon，避免两处重复。
 */
export function WriteToolbar({ onDictateInsert }: Props) {
  if (!onDictateInsert) return null;
  return (
    <div className={styles.toolbar} data-testid="write-toolbar-slim">
      <SpeechInputButton onInsert={onDictateInsert} />
      <span className={styles.hintInline}>格式切换、查找、改稿在顶栏「开始 / 审阅」</span>
    </div>
  );
}

export type WriteMode = "prose" | "rpy";
