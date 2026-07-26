"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useParams } from "next/navigation";
import type { VnProject } from "@vnss/core";
import {
  loadShare,
  saveShareFromFile,
  type SharePayload,
} from "@/lib/share";
import styles from "./share.module.css";

export default function SharePage() {
  const params = useParams();
  const id = String(params?.id ?? "");
  const [payload, setPayload] = useState<SharePayload | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (!id) return;
    const found = loadShare(id);
    if (found) {
      setPayload(found);
      setMissing(false);
    } else {
      setMissing(true);
    }
  }, [id]);

  function onFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(String(reader.result)) as SharePayload;
        if (!data?.id || !data.project) throw new Error("invalid");
        saveShareFromFile(data);
        setPayload(data);
        setMissing(false);
      } catch {
        alert("无法读取只读包");
      }
    };
    reader.readAsText(file);
  }

  if (!payload) {
    return (
      <div className={styles.wrap}>
        <h1>只读分享</h1>
        {missing ? (
          <p>
            本机未找到分享包 <code>{id}</code>。可请对方发来的{" "}
            <code>.vnss-share.json</code> 导入：
          </p>
        ) : (
          <p>加载中…</p>
        )}
        <label className={styles.fileBtn}>
          导入只读包
          <input
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onFile(f);
            }}
          />
        </label>
      </div>
    );
  }

  const p = payload.project;
  return (
    <div className={styles.wrap}>
      <header className={styles.head}>
        <p className={styles.badge}>只读设定包 · 无需会员</p>
        <h1>{p.title}</h1>
        <p className={styles.meta}>
          {p.genre || "未标题材"} · 分享于{" "}
          {new Date(payload.createdAt).toLocaleString()}
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
