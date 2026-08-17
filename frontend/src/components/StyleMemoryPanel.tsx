import { useState } from "react";
import { clearStyleMemory, learnStyleMemory } from "../api/projects";
import type { VnProject } from "../types/vn";
import styles from "./StyleMemoryPanel.module.css";

type Props = {
  project: VnProject;
  onChange: (p: VnProject) => void;
};

/**
 * 文风记忆：LLM 从作者自己的章节归纳风格指南，Agent 续写/改写自动贴合。
 * 纯展示 + 触发；状态与错误就地处理，不打断编辑。
 */
export function StyleMemoryPanel({ project, onChange }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  const memory = project.styleMemory;
  const guide = (memory?.guide ?? "").trim();
  const samples = memory?.samples ?? [];

  const learn = async () => {
    setBusy(true);
    setError("");
    setOk("");
    try {
      const res = await learnStyleMemory(project.id);
      onChange(res.project);
      setOk(
        res.guide
          ? "已从你的章节归纳文风，Agent 后续写作会自动贴合。"
          : "学习完成。"
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "文风学习失败");
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    setError("");
    setOk("");
    try {
      const res = await clearStyleMemory(project.id);
      onChange(res.project);
      setOk("已清除文风记忆。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "清除失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.wrap}>
      <p className={styles.hint}>
        AI 通读你的全文，归纳「你习惯怎么写」：句式节奏、用词、对白风格与应避免的套话。
        归纳结果注入 Agent 上下文，续写 / 改写 / 润色都会贴合你自己的文风。
      </p>
      {error && <p className={styles.error}>{error}</p>}
      {ok && <p className={styles.ok}>{ok}</p>}
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          disabled={busy}
          onClick={() => void learn()}
        >
          {busy ? "学习中…" : guide ? "重新学习文风" : "从全文学习文风"}
        </button>
        {guide && (
          <button
            type="button"
            className={styles.ghost}
            disabled={busy}
            onClick={() => void clear()}
          >
            清除记忆
          </button>
        )}
      </div>
      {guide ? (
        <div className={styles.card}>
          <header className={styles.cardHead}>
            <strong>文风记忆</strong>
            {memory?.updatedAt ? (
              <time>{new Date(memory.updatedAt).toLocaleString()}</time>
            ) : null}
          </header>
          <p className={styles.guide}>{guide}</p>
          {samples.length > 0 && (
            <ul className={styles.samples}>
              {samples.map((s, i) => (
                <li key={`${i}`}>「{s}」</li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        !busy && (
          <p className={styles.hint}>
            还没有文风记忆。写几章后点上方按钮，让 AI 学习你的写作习惯。
          </p>
        )
      )}
    </div>
  );
}
