import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { getShare, type ShareOut } from "../api/client";
import { FilingFooter } from "../components/FilingFooter";
import type { VnProject } from "../types/vn";
import { HELP_DISCLAIMER } from "../lib/helpContent";
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
  const previews = share.preview?.chapterPreviews ?? [];
  const base = previews.length > 0 ? 1 : 0;

  return (
    <div className={`vnss-app ${styles.wrap}`}>
      <header className={styles.head}>
        <div className={styles.arc} aria-hidden />
        <div className={styles.headInner}>
          <span className={styles.headIdx} aria-hidden>
            SH
          </span>
          <div className={styles.headCopy}>
            <p className={styles.badge}>作品发布页 · 无需会员</p>
            <h1>{p.title}</h1>
            <p className={styles.meta}>
              {p.genre || "未标题材"} · 分享于{" "}
              {new Date(share.created_at).toLocaleString()}
              {share.preview?.stats
                ? ` · ${share.preview.stats.chapters} 章 / 约 ${share.preview.stats.words} 字`
                : ""}
            </p>
            {p.logline && <p className={styles.logline}>{p.logline}</p>}
          </div>
        </div>
      </header>

      {previews.length > 0 && (
        <ShareSection idx="01" title="正文试读">
          <p className={styles.muted}>试读片段由作者发布时生成，正文仅展示节选。</p>
          <ChapterPreviewList previews={previews} />
        </ShareSection>
      )}

      <ShareSection idx={previews.length > 0 ? "02" : "01"} title="世界观">
        <pre>{p.bible?.world || p.lore || "—"}</pre>
      </ShareSection>
      <ShareSection idx={previews.length > 0 ? "03" : "02"} title="背景 / 大纲">
        <pre>{p.bible?.background || "—"}</pre>
        <pre>{p.bible?.outline || ""}</pre>
      </ShareSection>

      <ShareSection idx={String(3 + base)} title="角色">
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

      <ShareSection idx={String(4 + base)} title="地点">
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

      <ShareSection idx={String(5 + base)} title="变量 / 好感度">
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

      <ShareSection idx={String(6 + base)} title="立绘表情">
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

      <ShareSection idx={String(7 + base)} title="章节一览">
        <ChapterList project={p} />
      </ShareSection>
      <footer className={styles.footer}>
        <p>由 VN Script Studio 生成 · 只读发布</p>
        <p className={styles.disclaimer}>{HELP_DISCLAIMER}</p>
        <p>
          <Link to="/guide">使用指南</Link>
        </p>
        <FilingFooter />
      </footer>
    </div>
  );
}

function ChapterPreviewList({
  previews,
}: {
  previews: Array<{ chapterId: string; title: string; text: string }>;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <ul className={styles.list}>
      {previews.map((c) => {
        const open = openId === c.chapterId;
        return (
          <li key={c.chapterId} className={styles.previewItem}>
            <button
              type="button"
              className={styles.previewToggle}
              onClick={() => setOpenId(open ? null : c.chapterId)}
              aria-expanded={open}
            >
              <span>{c.title}</span>
              <span className={styles.muted}>{open ? "收起 ▲" : "试读 ▼"}</span>
            </button>
            {open && <pre className={styles.previewText}>{c.text}</pre>}
          </li>
        );
      })}
    </ul>
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
