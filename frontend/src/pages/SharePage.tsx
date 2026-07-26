import { useEffect, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { getShare, type ShareOut } from "../api/client";
import type { VnProject } from "../types/vn";
import styles from "./SharePage.module.css";

export default function SharePage() {
  const params = useParams();
  const token = String(params.token ?? "");
  const [share, setShare] = useState<ShareOut | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    getShare(token)
      .then((data) => {
        if (!cancelled) setShare(data);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "分享不存在或已失效");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (loading) {
    return (
      <div className={styles.wrap}>
        <h1>只读分享</h1>
        <p>加载中…</p>
      </div>
    );
  }

  if (error || !share) {
    return (
      <div className={styles.wrap}>
        <h1>只读分享</h1>
        <p>
          分享链接 <code>{token}</code> 无法打开：{error || "未找到"}
        </p>
      </div>
    );
  }

  const p: VnProject = share.project;

  return (
    <div className={styles.wrap}>
      <header className={styles.head}>
        <p className={styles.badge}>只读设定包 · 无需会员</p>
        <h1>{p.title}</h1>
        <p className={styles.meta}>
          {p.genre || "未标题材"} · 分享于{" "}
          {new Date(share.created_at).toLocaleString()}
        </p>
        {p.logline && <p className={styles.logline}>{p.logline}</p>}
      </header>

      <ShareSection title="世界观">
        <pre>{p.bible?.world || p.lore || "—"}</pre>
      </ShareSection>
      <ShareSection title="背景 / 大纲">
        <pre>{p.bible?.background || "—"}</pre>
        <pre>{p.bible?.outline || ""}</pre>
      </ShareSection>

      <ShareSection title="角色">
        <div className={styles.grid}>
          {p.characters.map((c) => (
            <article key={c.id} className={styles.card}>
              <h3 style={{ color: c.color }}>{c.displayName}</h3>
              <p>{c.bio || "无简介"}</p>
              {c.voice && <p className={styles.muted}>语气：{c.voice}</p>}
              {c.relationships && (
                <p className={styles.muted}>关系：{c.relationships}</p>
              )}
            </article>
          ))}
        </div>
      </ShareSection>

      <ShareSection title="地点">
        <ul className={styles.list}>
          {(p.locations ?? []).map((l) => (
            <li key={l.id}>
              <strong>{l.name}</strong>
              {l.imageTag ? ` · ${l.imageTag}` : ""}
              {l.description ? ` — ${l.description}` : ""}
            </li>
          ))}
          {(p.locations ?? []).length === 0 && <li>—</li>}
        </ul>
      </ShareSection>

      <ShareSection title="变量 / 好感度">
        <ul className={styles.list}>
          {(p.variables ?? []).map((v) => (
            <li key={v.id}>
              {v.name} (<code>{v.key}</code>) = {JSON.stringify(v.value)}
              {v.note ? ` · ${v.note}` : ""}
            </li>
          ))}
          {(p.variables ?? []).length === 0 && <li>—</li>}
        </ul>
      </ShareSection>

      <ShareSection title="立绘表情">
        <div className={styles.grid}>
          {(p.sprites ?? []).map((s) => (
            <article key={s.id} className={styles.card}>
              <h3>{s.name}</h3>
              <p>
                <code>{s.imageTag}</code>
              </p>
              <ul>
                {s.expressions.map((ex) => (
                  <li key={ex.id}>
                    {ex.name} → show {s.imageTag} {ex.tag}
                  </li>
                ))}
              </ul>
            </article>
          ))}
          {(p.sprites ?? []).length === 0 && <p>—</p>}
        </div>
      </ShareSection>

      <ShareSection title="章节一览（无正文）">
        <ChapterList project={p} />
      </ShareSection>
    </div>
  );
}

function ShareSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className={styles.section}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function ChapterList({ project }: { project: VnProject }) {
  return (
    <ul className={styles.list}>
      {project.chapters.map((c) => (
        <li key={c.id}>
          <strong>{c.title}</strong>
          {c.synopsis ? ` — ${c.synopsis}` : ""}
        </li>
      ))}
    </ul>
  );
}
