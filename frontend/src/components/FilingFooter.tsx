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
  // 公安备案按官方要求链到全国互联网安全管理服务平台的查询页，带上备案号里的数字编码
  const gonganCode = gongan?.replace(/[^0-9]/g, "") ?? "";

  return (
    <footer className={styles.filing}>
      <Link to="/guide">使用指南</Link>
      {icp ? (
        <a href="https://beian.miit.gov.cn" target="_blank" rel="noreferrer">
          {icp}
        </a>
      ) : null}
      {gongan ? (
        <a
          className={styles.gongan}
          href={
            gonganCode
              ? `https://beian.mps.gov.cn/#/query/webSearch?code=${gonganCode}`
              : "https://beian.mps.gov.cn"
          }
          target="_blank"
          rel="noreferrer"
        >
          {/* 公安备案图标（备案系统提供）：纯装饰，号码本身已经把信息说全了 */}
          <img
            className={styles.gonganIcon}
            src="/gongan-beian.png"
            alt=""
            width={14}
            height={16}
            loading="lazy"
          />
          {gongan}
        </a>
      ) : null}
    </footer>
  );
}
