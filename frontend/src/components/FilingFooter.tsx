import { useEffect, useState } from "react";

import { apiFetch } from "../api/http";
import styles from "./FilingFooter.module.css";

type SiteMeta = { icpBeian?: string; gonganBeian?: string };

/** 网站底部备案号（ICP / 公安）。服务端未配置时渲染为空。 */
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
  if (!icp && !gongan) return null;

  return (
    <footer className={styles.filing}>
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
