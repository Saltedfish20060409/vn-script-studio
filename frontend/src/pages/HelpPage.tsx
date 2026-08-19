import { Link } from "react-router-dom";
import { HELP_DISCLAIMER, HELP_FAQ, HELP_QUICK } from "../lib/helpContent";
import styles from "./HelpPage.module.css";

export default function HelpPage() {
  return (
    <div className={`vnss-app ${styles.page}`}>
      <header className={styles.head}>
        <p className={styles.kicker}>VN SCRIPT STUDIO</p>
        <h1>帮助与 FAQ</h1>
        <p className={styles.lead}>
          先写人话，再生成能上演的稿。下面按「怎么用」和常见问题排列。
        </p>
        <p className={styles.nav}>
          <Link to="/login">登录</Link>
          <Link to="/">进入工作室</Link>
        </p>
      </header>

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

      <p className={styles.disclaimer}>{HELP_DISCLAIMER}</p>
    </div>
  );
}
