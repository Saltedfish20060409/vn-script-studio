import { useEffect, useState } from "react";
import { listProjectTemplates, type ProjectTemplate } from "../api/projects";
import styles from "./TemplatePicker.module.css";

type Props = {
  onPick: (templateId: string) => void;
  busy?: boolean;
};

/**
 * Starter template picker — fetches the template catalogue and lets the user
 * start a new project from a genre scaffold (日常/悬疑/异世界…).
 */
export function TemplatePicker({ onPick, busy }: Props) {
  const [templates, setTemplates] = useState<ProjectTemplate[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    listProjectTemplates()
      .then((res) => {
        if (!cancelled) setTemplates(res.templates);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "模板加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <p className={styles.error}>{error}</p>;
  if (!templates) return <p className={styles.hint}>加载模板…</p>;

  return (
    <div className={styles.wrap}>
      <p className={styles.hint}>从模板开始，几秒内就有一章可写的内容：</p>
      <div className={styles.grid}>
        {templates.map((t) => (
          <button
            key={t.id}
            type="button"
            className={styles.card}
            disabled={busy}
            onClick={() => onPick(t.id)}
            title={`${t.genre} · ${t.logline}`}
          >
            <strong className={styles.title}>{t.title}</strong>
            <span className={styles.genre}>{t.genre}</span>
            <span className={styles.logline}>{t.logline}</span>
            <span className={styles.chars}>{t.characters.join("、")}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
