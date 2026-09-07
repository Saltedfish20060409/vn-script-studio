import type { HarnessPrefs } from "../lib/harnessPrefs";
import { AgentMessageBody } from "./AgentMarkdown";
import styles from "./AgentChat.module.css";

type Props = {
  prefs: HarnessPrefs;
  onPrefsChange: (next: HarnessPrefs) => void;
  onClose: () => void;
};

const HELP_MD = `### 责编能帮你做什么

写作页右下角的 AI 编辑，能读当前章节和你选中的段落。用平常话吩咐即可，它能做这些事：

1. **润色 / 改写 / 续写**：说「帮我润色这段」「按这个感觉接着写」——它先出**改稿草稿**并弹左右对照，满意点「写入」、不满意点「丢弃」，不会直接污染你的原稿；确认写入后稿子自动进写作页面，不用复制粘贴。
2. **审稿挑毛病**：说「审一下这章」——按轻小说 / 视觉小说标准找问题（对白生硬、钩子弱、说明书腔、设定矛盾等），默认只给意见不动稿。
3. **换作家眼光**：点顶部 **⇄** 挑一位作家卡，后续按它的视角看稿（内置 15 位：文学氛围、悬疑社会派、学园恋爱、催泪系等）。
4. **头脑风暴**：开「多选」选 2～3 位作家，填个议题，让各家**独立发言**后由责编综合成共识与行动建议。
5. **整理设定 / 附件**：说「把这段整理进关系表 / 时间线」，或传份资料说「按附件更新设定」。
6. **改坏能撤**：Agent 写入后，消息下方有「撤回编辑（N 步）」，一步回到写入前。

不换任何作家视角时，默认的「通用文学编辑」会自动按一套轻小说 / 视觉小说的写作要点帮你看稿（对白要能演得动、每场留个让人想读下去的钩子、别把设定像说明书一样倒出来）——这些你不用管，说人话就行。

### 推荐写作流程

1. **直接聊**：说清场次或卡点。  
2. **（可选）换作家眼光**：点顶部 **⇄**，挑一位作家视角（可开多选做头脑风暴）。  
3. **文风体检**（可选）：扫问题不改文。  
4. **定稿**：AI 先做自动检查，通过后把改动写进正文并记入变更记录。

### 怎么说话

用平常话说即可，例如「根据附件更新设定」「帮我改这一章更有人味」「整理关系进待审」。需要改章时直接说，会出现模式选择与对照挑选弹窗。

### 卡壳时的替代

「自动写作：……」适合没思路或要一整场戏——**不是**日常必经步骤。

### 强头脑风暴

1. 点 **⇄** → 打开「多选」→ 选 2～3 位作家  
2. 填写议题，点「开始头脑风暴」，或直接说「头脑风暴：下一场怎么拆」  
3. 程序会让每位作家**各自独立调用一次模型**（互相看不见），再由责编综合分歧与三步行动  

这与「一次对话里塞多个视角」不同，是真正的分视角圆桌。

### 作家卡从哪来

内置 15 位作家的视角（每张卡是一套公开写作技法的启发视角，不是作家本人，禁止仿写原文）。想自制更多视角的高级用户：用 [女娲.skill](https://github.com/alchaincyf/nuwa-skill) 离线把作家技法蒸馏成卡再导入工程（流程见仓库 \`backend/vendor/NUWA_LENS_WORKFLOW.md\`）。

冲突时：**你作品里定的硬规则 > 通用编辑 > 所选作家视角**。`;

/** 功能说明弹层：Harness 纪律偏好 + 推荐流程 markdown。纯展示。 */
export function AgentHelpOverlay({ prefs, onPrefsChange, onClose }: Props) {
  return (
    <div className={styles.stageOverlay} role="dialog" aria-modal="true">
      <header className={styles.overlayHead}>
        <div>
          <p className={styles.overlayIdx}>HELP</p>
          <h3 className={styles.overlayTitle}>功能说明</h3>
        </div>
        <button type="button" className={styles.hudBtn} onClick={onClose}>
          关闭
        </button>
      </header>
      <div className={styles.harnessPrefs}>
        <p className={styles.harnessPrefsTitle}>定稿纪律（进阶）</p>
        <label className={styles.harnessToggle}>
          <input
            type="checkbox"
            checked={Boolean(prefs.voiceHard)}
            onChange={(e) => onPrefsChange({ ...prefs, voiceHard: e.target.checked })}
          />
          <span>
            声线硬门禁
            <small>对白明显不像这个角色（破人设）时，直接拦下，不写入正文</small>
          </span>
        </label>
        <label className={styles.harnessToggle}>
          <input
            type="checkbox"
            checked={prefs.voiceCheck !== false}
            onChange={(e) => onPrefsChange({ ...prefs, voiceCheck: e.target.checked })}
          />
          <span>
            终检声线
            <small>自动写作 / 定稿收尾时，自动检查对白像不像角色</small>
          </span>
        </label>
        <label className={styles.harnessToggle}>
          <span className={styles.harnessRounds}>
            修正轮次
            <select
              value={prefs.maxReviseRounds ?? 2}
              onChange={(e) =>
                onPrefsChange({
                  ...prefs,
                  maxReviseRounds: Number(e.target.value),
                })
              }
            >
              {[0, 1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </span>
        </label>
      </div>
      <AgentMessageBody content={HELP_MD} mode="markdown" />
    </div>
  );
}
