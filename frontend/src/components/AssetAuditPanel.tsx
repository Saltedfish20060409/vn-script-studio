import { useCallback, useEffect, useState } from "react";
import { fetchAssetAudit, type AssetAuditOut } from "../api/projects";
import { ApiError } from "../api/http";
import styles from "./AssetAuditPanel.module.css";

type Props = {
  projectId: string;
  onOpenChapter?: (chapterId: string) => void;
};

const AUDIO_LABEL: Record<string, string> = {
  music: "BGM",
  sound: "音效",
  voice: "语音",
};

/**
 * 素材清单与引用审计。
 *
 * 说明（不夸大）：项目里没有素材上传与存储，剧本用**名字/路径**引用素材。
 * 这一页给的是"要去准备哪些文件"的完整清单，并把图像名对不上任何立绘/角色 tag
 * 的可疑条目挑出来（多半是拼错，Ren'Py 里会表现为运行时缺图）。
 */
export function AssetAuditPanel({ projectId, onOpenChapter }: Props) {
  const [data, setData] = useState<AssetAuditOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setData(await fetchAssetAudit(projectId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data) {
    return <p className={styles.note}>{error || (busy ? "正在统计素材引用…" : "")}</p>;
  }

  const audioTotal = Object.values(data.audio).reduce((n, a) => n + a.total, 0);

  return (
    <div className={styles.wrap} data-testid="asset-audit">
      <div className={styles.head}>
        <strong className={styles.title}>素材清单与引用审计</strong>
        <button type="button" className={styles.btn} onClick={() => void load()} disabled={busy}>
          {busy ? "统计中…" : "重新统计"}
        </button>
      </div>

      <div className={styles.cards}>
        <div className={styles.card}>
          <span>图像引用</span>
          <strong>{data.images.total}</strong>
        </div>
        <div className={styles.card}>
          <span>音频引用</span>
          <strong>{audioTotal}</strong>
        </div>
        <div className={styles.card}>
          <span>疑似写错</span>
          <strong className={data.images.suspicious.length ? styles.bad : undefined}>
            {data.images.suspicious.length}
          </strong>
        </div>
        <div className={styles.card}>
          <span>声明未用</span>
          <strong>{data.unusedTags.length}</strong>
        </div>
      </div>

      {data.images.suspicious.length > 0 ? (
        <div className={styles.block}>
          <span className={styles.blockTitle}>
            疑似写错的图像名（对不上任何立绘/角色 imageTag）
          </span>
          <ul className={styles.list}>
            {data.images.suspicious.map((s) => (
              <li key={s.image}>
                <code>{s.image}</code>
                <span className={styles.dim}>用了 {s.uses} 次</span>
                {s.chapters[0] ? (
                  <button
                    type="button"
                    className={styles.link}
                    onClick={() => onOpenChapter?.(s.chapters[0])}
                  >
                    去看
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className={styles.block}>
        <span className={styles.blockTitle}>要准备的图像（{data.images.total}）</span>
        <ul className={styles.list}>
          {data.images.items.map((i) => (
            <li key={i.image}>
              <code>{i.image}</code>
              <span className={styles.dim}>×{i.uses}</span>
            </li>
          ))}
        </ul>
      </div>

      {Object.entries(data.audio).map(([kind, group]) =>
        group.total > 0 ? (
          <div className={styles.block} key={kind}>
            <span className={styles.blockTitle}>
              {AUDIO_LABEL[kind] ?? kind}（{group.total}）
            </span>
            <ul className={styles.list}>
              {group.items.map((i) => (
                <li key={i.file}>
                  <code>{i.file}</code>
                  <span className={styles.dim}>×{i.uses}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null
      )}

      {data.unusedTags.length > 0 ? (
        <div className={styles.block}>
          <span className={styles.blockTitle}>声明了但剧本里没用到的 tag</span>
          <ul className={styles.list}>
            {data.unusedTags.map((t) => (
              <li key={t}>
                <code>{t}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {data.notes.map((n, i) => (
        <p className={styles.note} key={i}>
          {n}
        </p>
      ))}
    </div>
  );
}
