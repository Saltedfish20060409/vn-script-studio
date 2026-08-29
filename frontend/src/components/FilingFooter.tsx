import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../api/http";
import styles from "./FilingFooter.module.css";

type SiteMeta = { icpBeian?: string; gonganBeian?: string };

/** 网站底部：使用指南链接 + 备案号（ICP / 公安）。服务端未配置备案号时隐藏备案部分。 */
export function FilingFooter() {
  const [meta, setMeta] = useState<SiteMeta | null>(null);

  useEffect(() => {
    let alive = true;
    apiFetch<SiteMeta>("/meta")
      .then((m) => {
        if (alive) setMeta(m);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  const icp = meta?.icpBeian?.trim();
  const gongan = meta?.gonganBeian?.trim();

  return (
    <footer className={styles.filing}>
      <Link to="/guide">使用指南</Link>
      {icp ? (
        <a href="https://beian.miit.gov.cn" target="_blank" rel="noreferrer">
          {icp}
        </a>
      ) : null}
      {gongan ? (
        <a href="https://www.beian.gov.cn" target="_blank" rel="noreferrer">
          {gongan}
        </a>
      ) : null}
    </footer>
  );
}
