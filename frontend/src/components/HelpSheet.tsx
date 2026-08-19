import { MascotFigure } from "./MascotFigure";
import styles from "./HelpSheet.module.css";

type Props = {
  open: boolean;
  onClose: () => void;
};

const SECTIONS: Array<{ title: string; body: string }> = [
  {
    title: "写作：剧本 / RPY",
    body: "写作页默认是自然语言剧本，像小说或台本那样写即可：旁白直接写，对白写成「角色名：台词」。同一编辑器可切到 RPY：两份稿互不覆盖。RPY 可以手写，也可以点「根据剧本生成」（已配置模型时走 AI，否则用规则解析）。剧本改过而 RPY 没重生时会提示过期。试玩读的是 RPY 稿，只写了自然语言时请先生成或手写脚本。",
  },
  {
    title: "导出跟当前视图",
    body: "顶栏导出按你正在看的稿走：剧本视图下载 .docx，RPY 视图下载 .rpy。整包工程、Markdown、Ren'Py 项目 zip 仍在「项目 → 导出」。",
  },
  {
    title: "设定、地图、角色工坊",
    body: "「设定」写角色卡和世界观；「地图」从剧本抽地点，点地点可跳回写作。「角色工坊」先定声音、再合成思维包，然后试聊。手机上名单收成抽屉：顶上始终显示当前角色，点「换角色」打开名单。",
  },
  {
    title: "AI 编辑与设置",
    body: "桌面上 Agent 多在右下角；手机上是屏幕侧边的贴片，点开即可。不确定时可以直接说「先不要改工程，只给意见」。模型 Key 在左下角齿轮 → 模型。用量、外观也在设置里。",
  },
  {
    title: "协作与账号",
    body: "「协作」可邀请成员、锁章节、批注。注册需验证邮箱后才能登录；忘记密码走登录页的找回流程。",
  },
];

export function HelpSheet({ open, onClose }: Props) {
  if (!open) return null;
  return (
    <div
      className={styles.backdrop}
      role="dialog"
      aria-modal="true"
      aria-labelledby="help-sheet-title"
      onClick={onClose}
    >
      <div className={styles.sheet} onClick={(e) => e.stopPropagation()}>
        <div className={styles.mascot} aria-hidden>
          <MascotFigure size="md" mood="cheer" line="先写人话，再生成能上演的稿。" />
        </div>
        <div className={styles.body}>
          <p className={styles.idx}>HOW TO</p>
          <h2 id="help-sheet-title" className={styles.title}>
            使用说明
          </h2>
          <div className={styles.sections}>
            {SECTIONS.map((s) => (
              <section key={s.title}>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </section>
            ))}
          </div>
          <div className={styles.actions}>
            <button type="button" className={styles.primary} onClick={onClose}>
              知道了
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
