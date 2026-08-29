import { Link } from "react-router-dom";
import { TiltedCard } from "../components/reactbits/TiltedCard";
import { HELP_DISCLAIMER, HELP_FAQ, HELP_QUICK } from "../lib/helpContent";
import styles from "./HelpPage.module.css";

/** 反馈渠道（集中维护，改这里即可全站生效） */
const QQ_CONTACT = "464313944";
const GITHUB_URL = "https://github.com/Saltedfish20060409/vn-script-studio";
const FEEDBACK_EMAIL = "464313944@qq.com";

export default function HelpPage() {
  return (
    <div className={`vnss-app ${styles.page}`}>
      <TiltedCard maxTilt={4} className={styles.tiltWrap}>
        <header className={styles.head}>
          <p className={styles.kicker}>VN SCRIPT STUDIO</p>
          <h1>帮助与 FAQ</h1>
          <p className={styles.lead}>
            先写人话，再生成能上演的稿。下面按「怎么用」和常见问题排列。
          </p>
          <p className={styles.nav}>
            <Link to="/guide">完整使用指南</Link>
            <Link to="/login">登录</Link>
            <Link to="/">进入工作室</Link>
          </p>
        </header>
      </TiltedCard>

      <section className={styles.block}>
        <h2>怎么用</h2>
        {HELP_QUICK.map((s) => (
          <article key={s.title}>
            <h3>{s.title}</h3>
            <p>{s.body}</p>
          </article>
        ))}
      </section>

      <section className={styles.block}>
        <h2>常见问题</h2>
        {HELP_FAQ.map((item) => (
          <details key={item.q} className={styles.faq}>
            <summary>{item.q}</summary>
            <p>{item.a}</p>
          </details>
        ))}
      </section>

      <section className={styles.block}>
        <h2>联系我们 / 反馈</h2>
        <article>
          <h3>QQ</h3>
          <p>
            使用中遇到问题、想提功能建议，欢迎直接加作者 QQ：
            <strong> {QQ_CONTACT} </strong>
            （加好友时备注「VNSS 反馈」）。
          </p>
        </article>
        <article>
          <h3>GitHub</h3>
          <p>
            项目开源，欢迎提交 Issue（bug / 建议）或 Pull Request：
            <br />
            <a href={GITHUB_URL} target="_blank" rel="noreferrer">
              github.com/Saltedfish20060409/vn-script-studio
            </a>
          </p>
        </article>
        <article>
          <h3>邮件</h3>
          <p>
            不方便加群？发邮件到 <strong> {FEEDBACK_EMAIL} </strong>，标题注明「VNSS 反馈」。
          </p>
        </article>
      </section>

      <p className={styles.disclaimer}>{HELP_DISCLAIMER}</p>
    </div>
  );
}
