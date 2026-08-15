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
      <div className={`vnss-app ${styles.wrap}`}>
        <header className={styles.head}>
          <div className={styles.arc} aria-hidden />
          <div className={styles.headInner}>
            <span className={styles.headIdx} aria-hidden>
              SH
            </span>
            <div className={styles.headCopy}>
              <h1>只读分享</h1>
              <p className={styles.statusMsg}>加载中…</p>
            </div>
          </div>
        </header>
      </div>
    );
  }

  if (error || !share) {
    return (
      <div className={`vnss-app ${styles.wrap}`}>
        <header className={styles.head}>
          <div className={styles.arc} aria-hidden />
          <div className={styles.headInner}>
            <span className={styles.headIdx} aria-hidden>
              SH
            </span>
            <div className={styles.headCopy}>
              <h1>只读分享</h1>
              <p className={styles.statusMsg}>
                分享链接 <code>{token}</code> 无法打开：{error || "未找到"}
              </p>
            </div>
          </div>
        </header>
      </div>
    );
  }

  const p: VnProject = share.project;

  return (
    <div className={`vnss-app ${styles.wrap}`}>
      <header className={styles.head}>
        <div className={styles.arc} aria-hidden />
        <div className={styles.headInner}>
          <span className={styles.headIdx} aria-hidden>
            SH
          </span>
          <div className={styles.headCopy}>
            <p className={styles.badge}>只读设定包 · 无需会员</p>
            <h1>{p.title}</h1>
            <p className={styles.meta}>
              {p.genre || "未标题材"} · 分享于{" "}
              {new Date(share.created_at).toLocaleString()}
            </p>
            {p.logline && <p className={styles.logline}>{p.logline}</p>}
          </div>
        </div>
      </header>

      <ShareSection idx="01" title="世界观">
        <pre>{p.bible?.world || p.lore || "—"}</pre>
      </ShareSection>
      <ShareSection idx="02" title="背景 / 大纲">
        <pre>{p.bible?.background || "—"}</pre>
        <pre>{p.bible?.outline || ""}</pre>
      </ShareSection>

      <ShareSection idx="03" title="角色">
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

      <ShareSection idx="04" title="地点">
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

      <ShareSection idx="05" title="变量 / 好感度">
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

      <ShareSection idx="06" title="立绘表情">
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

      <ShareSection idx="07" title="章节一览（无正文）">
        <ChapterList project={p} />
      </ShareSection>
    </div>
  );
}

function ShareSection({
  idx,
  title,
  children,
}: {
  idx: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className={styles.section}>
      <header className={styles.sectionHead}>
        <span className={styles.sectionIdx} aria-hidden>
          {idx}
        </span>
        <h2 className={styles.sectionTitle}>{title}</h2>
      </header>
      <div className={styles.sectionBody}>{children}</div>
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
