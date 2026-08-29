import { Link, useSearchParams } from "react-router-dom";
import styles from "./LegalPage.module.css";

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className={styles.block}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return <p>{children}</p>;
}

export default function LegalPage() {
  const [params] = useSearchParams();
  const doc = params.get("doc") === "terms" ? "terms" : "privacy";

  return (
    <div className={`vnss-app ${styles.wrap}`}>
      <main className={styles.paper}>
        <p className={styles.kicker}>VN SCRIPT STUDIO</p>
        <h1>{doc === "terms" ? "服务条款" : "隐私政策"}</h1>
        <p className={styles.updated}>最后更新：2026 年 8 月</p>

        {doc === "privacy" ? (
          <>
            <Block title="1. 我们收集什么">
              <P>
                注册时你提供的用户名与邮箱地址；使用编辑器时保存在你账号下的项目、
                章节、设定与 AI 对话记录；音乐功能中你自行导入的 Cookie（仅存于你的浏览器，
                不上传服务器）。我们不会收集你的密码明文（仅存哈希）。
              </P>
            </Block>
            <Block title="2. 这些数据用来做什么">
              <P>
                账号注册与登录、云端同步你的剧本与项目、AI 写作与审稿功能、
                发送验证/找回邮件。音乐 Cookie 仅在你自己的浏览器内用于请求歌曲直链，
                服务器不存储、不记录。
              </P>
            </Block>
            <Block title="3. 我们不会做什么">
              <P>
                不出售你的个人信息；不用你的剧本训练他人模型；不向第三方共享你的项目内容，
                除非法律要求。你导入的 AI 模型密钥仅保存在你本机浏览器。
              </P>
            </Block>
            <Block title="4. 数据保存与删除">
              <P>
                删除账号会同时删除你名下的项目与对话记录，操作不可恢复。你可以随时联系我们
                要求导出或清除数据。
              </P>
            </Block>
            <Block title="5. 第三方服务">
              <P>
                站点部署于云服务器；发送邮件使用 Resend；音乐直链由网易云/酷狗/B站 提供，
                受其各自条款约束。AI 生成内容可能带有不确定性，请自行审稿后使用。
              </P>
            </Block>
            <Block title="6. 联系我们">
              <P>如有隐私问题，可通过站点内「使用指南」中登记的联系方式与我们联系。</P>
            </Block>
          </>
        ) : (
          <>
            <Block title="1. 服务说明">
              <P>
                VN Script Studio 提供视觉小说/轻小说写作的云端工具：编辑器、AI 辅助写作与审稿、
                协作分享、音乐播放等。服务可能随时调整或停止，重大变更会提前公告。
              </P>
            </Block>
            <Block title="2. 账号与责任">
              <P>
                你负责保管自己的账号密码与 API 密钥。使用 AI 生成的剧本、设定或任何内容，
                发布前请自行审稿并确认符合相关平台与法律法规（包括但不限于版权、未成年人内容等）。
              </P>
            </Block>
            <Block title="3. 合理使用">
              <P>
                不得利用本站存储、生成或分发违法、侵权、恶意内容；不得攻击服务、爬取其他用户
                数据或滥用接口。违反者账号可能被停用。
              </P>
            </Block>
            <Block title="4. AI 内容免责">
              <P>
                AI 输出可能包含事实错误、风格偏差或不当内容，本站不对生成内容作正确性承诺。
                音乐歌词/直链来自第三方平台，可用性以平台为准。
              </P>
            </Block>
            <Block title="5. 服务可用性">
              <P>
                我们尽力保证稳定，但不承诺无中断。付费功能（如有）的退款规则另行说明。
              </P>
            </Block>
            <Block title="6. 条款变更">
              <P>条款更新后会在本页展示最新版本，继续使用服务即视为接受更新后的条款。</P>
            </Block>
          </>
        )}

        <div className={styles.foot}>
          <Link to="/login">← 返回登录</Link>
          <span aria-hidden> · </span>
          <Link to="/legal?doc=privacy">隐私政策</Link>
          <span aria-hidden> · </span>
          <Link to="/legal?doc=terms">服务条款</Link>
        </div>
      </main>
    </div>
  );
}
