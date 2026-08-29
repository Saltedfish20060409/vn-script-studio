import { useMemo } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { TiltedCard } from "../components/reactbits/TiltedCard";
import GUIDE_MD from "../lib/guide.md?raw";
import styles from "./GuidePage.module.css";

type TocEntry = { id: string; title: string };

/** 从 Markdown 的 ## 标题构建目录；锚点 id 与渲染时的 slug 保持一致。 */
function buildToc(md: string): TocEntry[] {
  const out: TocEntry[] = [];
  for (const line of md.split("\n")) {
    const m = /^##\s+(.+)$/.exec(line.trim());
    if (!m) continue;
    const title = m[1].trim();
    const id = slugify(title);
    out.push({ id, title });
  }
  return out;
}

function slugify(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
}

export default function GuidePage() {
  const toc = useMemo(() => buildToc(GUIDE_MD), []);

  return (
    <div className={`vnss-app ${styles.page}`}>
      <TiltedCard maxTilt={3} className={styles.tiltWrap}>
        <header className={styles.head}>
          <p className={styles.kicker}>VN SCRIPT STUDIO</p>
          <h1>使用说明</h1>
          <p className={styles.lead}>
            从注册到导出，每个页面的完整用法。按章节顺序读，或从左侧目录跳到你关心的部分。
          </p>
          <p className={styles.nav}>
            <Link to="/login">登录</Link>
            <Link to="/help">帮助与 FAQ</Link>
            <Link to="/">进入工作室</Link>
          </p>
        </header>
      </TiltedCard>

      <div className={styles.layout}>
        <nav className={styles.toc} aria-label="目录">
          <strong className={styles.tocTitle}>目录</strong>
          <ul>
            {toc.map((e) => (
              <li key={e.id}>
                <a href={`#${e.id}`}>{e.title}</a>
              </li>
            ))}
          </ul>
        </nav>

        <article className={styles.article}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              h2: ({ children }) => (
                <h2 id={slugify(String(children ?? ""))}>{children}</h2>
              ),
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              ),
            }}
          >
            {GUIDE_MD}
          </ReactMarkdown>
        </article>
      </div>
    </div>
  );
}
