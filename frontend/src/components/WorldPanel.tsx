import { useState } from "react";
import { ColorPicker } from "./ColorPicker";
import { LorePanel } from "./LorePanel";
import { LoreEntriesPanel } from "./LoreEntriesPanel";
import type { Character, LoreEntry, StoryBible } from "../types/vn";
import type { LoreLinkOption } from "../lib/loreEntries";
import { genreOptions } from "../lib/genreCopy";
import { GENRE_MAX, isOverLimit, overLimitHint } from "../lib/fieldLimits";
import { ConstraintAuditCard } from "./ConstraintAuditCard";
import styles from "./StudioApp.module.css";

type WorldSub = "characters" | "bible" | "lore" | "entries";

type Props = {
  worldSub: WorldSub;
  projectId: string;
  characters: Character[];
  logline: string;
  genre: string;
  bible: StoryBible;
  /** 设定条目：可堆很多条，AI 按触发词检索 */
  loreEntries: LoreEntry[];
  onSelectCharacters: () => void;
  onSelectBible: () => void;
  onSelectLore: () => void;
  onSelectEntries: () => void;
  onAddCharacter: () => void;
  onDeleteCharacter: (id: string) => void;
  onUpdateCharacter: (id: string, patch: Partial<Character>) => void;
  onLoglineChange: (value: string) => void;
  onGenreChange: (value: string) => void;
  /**
   * 作品体裁：决定界面用哪套词（剧本 / 正文·分卷·投稿）。
   * 默认按题材自动判断；作者在这里可以显式指定。
   */
  writingGenre?: "auto" | "vn" | "novel";
  onWritingGenreChange?: (value: "auto" | "vn" | "novel") => void;
  onBibleChange: (patch: Partial<StoryBible>) => void;
  onLoreEntriesChange: (next: LoreEntry[]) => void;
  /** 可关联的实体（角色/地点/章节）：设定条目用它点名"这条讲的是谁/在哪" */
  loreLinkOptions?: LoreLinkOption[];
  /** 有没有文风样例（约束体检据此提醒"补样例"） */
  hasStyleSamples?: boolean;
};

/**
 * 设定 tab: 角色卡 / 世界观 · 大纲 / 设定条目 三个常驻页，
 * 外加收在「更多」里的「写作参考卡」（进阶：教 AI 怎么写，不是"你的设定"）。
 * Pure presentational — update/delete logic stays in StudioApp.
 */
export function WorldPanel({
  worldSub,
  projectId,
  characters,
  logline,
  genre,
  bible,
  loreEntries,
  onSelectCharacters,
  onSelectBible,
  onSelectLore,
  onSelectEntries,
  onAddCharacter,
  onDeleteCharacter,
  onUpdateCharacter,
  onLoglineChange,
  onGenreChange,
  writingGenre,
  onWritingGenreChange,
  onBibleChange,
  onLoreEntriesChange,
  loreLinkOptions = [],
  hasStyleSamples = false,
}: Props) {
  const entriesBadge = loreEntries.length ? String(loreEntries.length) : "";
  // 「写作参考卡」是进阶功能（教 AI 怎么写），原来和「设定条目」（你的设定库）并列，
  // 两个名字只差一个字、意思完全不同，是"看不懂"的重灾区。现在它收进「更多」。
  // 注意：「更多」按钮必须一直在（能开能关）——上一版展开后按钮自己消失，点开就收不回来。
  const [moreOpen, setMoreOpen] = useState(false);
  return (
    <>
      <div className={styles.subNav} style={{ padding: "0.75rem 1.1rem 0" }}>
        <button
          type="button"
          className={worldSub === "characters" ? styles.subActive : styles.subTab}
          onClick={onSelectCharacters}
        >
          角色卡
        </button>
        <button
          type="button"
          className={worldSub === "bible" ? styles.subActive : styles.subTab}
          onClick={onSelectBible}
        >
          世界观 / 大纲
        </button>
        <button
          type="button"
          className={worldSub === "entries" ? styles.subActive : styles.subTab}
          onClick={onSelectEntries}
        >
          设定条目{entriesBadge ? `（${entriesBadge}）` : ""}
        </button>
        {/* 进阶：教 AI 怎么写（不是"你的设定"），所以排在最后并默认收起。
            「更多」始终在、能开能关；当前正停在这一页时即使收起也留着它，
            免得"页面在写作参考卡、却看不见自己在哪"。 */}
        {worldSub === "lore" || moreOpen ? (
          <button
            type="button"
            className={worldSub === "lore" ? styles.subActive : styles.subTab}
            onClick={onSelectLore}
          >
            写作参考卡
          </button>
        ) : null}
        <button
          type="button"
          className={styles.subTab}
          data-testid="world-subs-more"
          aria-expanded={moreOpen}
          onClick={() => setMoreOpen((v) => !v)}
        >
          {moreOpen ? "收起 ‹" : "更多 ›"}
        </button>
      </div>
      {worldSub === "characters" && (
        <section className={styles.panel}>
          <div className={styles.toolbar}>
            <span>角色卡（删除不会自动改写对白）</span>
            <button type="button" className={styles.primary} onClick={onAddCharacter}>
              添加角色
            </button>
          </div>
          <div className={styles.charGrid}>
            {characters.map((c) => (
              <article key={c.id} className={styles.charCard}>
                <div className={styles.cardHead}>
                  <strong>{c.displayName || "未命名"}</strong>
                  <button
                    type="button"
                    className={styles.danger}
                    onClick={() => onDeleteCharacter(c.id)}
                  >
                    删除
                  </button>
                </div>
                <label>
                  显示名
                  <input
                    value={c.displayName}
                    onChange={(e) =>
                      onUpdateCharacter(c.id, {
                        displayName: e.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  <span>
                    define 名
                    <small style={{ fontWeight: 400, opacity: 0.75 }}>
                      （生成的 Ren'Py 剧本用这个名字指代角色；只填英文、数字、下划线，如 linxia）
                    </small>
                  </span>
                  <input
                    value={c.defineName}
                    onChange={(e) =>
                      onUpdateCharacter(c.id, {
                        defineName: e.target.value.replace(/[^A-Za-z0-9_]/g, ""),
                      })
                    }
                    placeholder="如 linxia"
                  />
                </label>
                <label>
                  颜色
                  <ColorPicker
                    value={c.color ?? "#6b7280"}
                    onChange={(color) => onUpdateCharacter(c.id, { color })}
                  />
                </label>
                <label>
                  语气
                  <textarea
                    rows={2}
                    value={c.voice ?? ""}
                    onChange={(e) => onUpdateCharacter(c.id, { voice: e.target.value })}
                  />
                </label>
                <label>
                  简介
                  <textarea
                    rows={3}
                    value={c.bio ?? ""}
                    onChange={(e) => onUpdateCharacter(c.id, { bio: e.target.value })}
                  />
                </label>
                <label>
                  人物关系
                  <textarea
                    rows={2}
                    value={c.relationships ?? ""}
                    onChange={(e) =>
                      onUpdateCharacter(c.id, {
                        relationships: e.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  <span>
                    别的叫法
                    <small style={{ fontWeight: 400, opacity: 0.75 }}>
                      （绰号、旧名、称呼；逗号分隔。AI 检索会一并命中——设定里换了叫法也能找到）
                    </small>
                  </span>
                  <input
                    value={(c.aliases ?? []).join("、")}
                    onChange={(e) =>
                      onUpdateCharacter(c.id, {
                        aliases: e.target.value
                          .split(/[、,，;；\s]+/)
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                    placeholder="如 阿雪、雪师姐"
                  />
                </label>
              </article>
            ))}
          </div>
        </section>
      )}
      {worldSub === "bible" && (
        <section className={styles.panel}>
          <div className={styles.toolbar}>
            {/* 这段以前写的是「每格有长度上限，超出会被截断」——没说清截的是什么，
                读到的人会以为**保存**会把世界观 / 大纲砍掉。实际不会：这几个框想写多长都存得下，
                被截的是"送进 AI 的那一份"（世界观 _clip 900；背景 500；主题、备忘各 300；
                大纲走 select_outline_beats：按行切成节拍、只带相关的那几条，见 core/agent_context.py）。
                说的和做的不一样，就会让人不敢写。 */}
            <span title="这几个框想写多长都能存。AI 每次只读到其中一小段：世界观约 900 字；大纲按「一行一条节拍」检索，只带上相关的那几条。超出部分它看不到，但你的原文一个字都不会丢。">
              设定越全，AI 越少瞎猜。这几个框<strong>存得下多少都行</strong>——AI 每次只读其中一小段：
              世界观约 900 字；<strong>大纲写成一行一条节拍</strong>时按相关度检索，只带相关的几条。
              读不到的部分不会丢，只是这一轮没进它的视野。
              <strong>设定体量大就改用「设定条目」</strong>——那里能堆很多条，AI 按触发词只取相关的几条。
            </span>
          </div>
          <div className={styles.bibleGrid}>
            <label>
              Logline（一句话）
              <input
                value={logline}
                onChange={(e) => onLoglineChange(e.target.value)}
              />
            </label>
            <label>
              类型 / 题材
              {/* maxLength 是"别让用户白打一遍字"的第一道门；上限与后端
                  varchar(128) 一致（见 lib/fieldLimits.ts 的注释）。
                  存量超长值（上次粘贴留下的）靠下面那条就地提醒——不能等一次失败的保存
                  才告诉用户（那次故障里用户连"哪一项"都不知道）。 */}
              <input
                value={genre}
                maxLength={GENRE_MAX}
                onChange={(e) => onGenreChange(e.target.value)}
              />
              {isOverLimit(genre, GENRE_MAX) ? (
                <span className={styles.fieldWarn} role="status">
                  {overLimitHint("类型 / 题材", genre, GENRE_MAX)}
                </span>
              ) : null}
            </label>
            {onWritingGenreChange ? (
              <label
                className={styles.full}
                title="决定界面里的用词：视觉小说用「剧本 / 选项」，小说用「正文 / 分卷 / 投稿」"
              >
                界面用词
                <select
                  value={writingGenre ?? "auto"}
                  onChange={(e) =>
                    onWritingGenreChange(e.target.value as "auto" | "vn" | "novel")
                  }
                >
                  {genreOptions({ genre, writingGenre }).map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label} — {opt.hint}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <label className={styles.full}>
              世界观
              <textarea
                rows={4}
                value={bible.world ?? ""}
                onChange={(e) => onBibleChange({ world: e.target.value })}
                placeholder="世界规则、时代、超自然设定…"
              />
            </label>
            <label className={styles.full}>
              故事背景 / 前情
              <textarea
                rows={4}
                value={bible.background ?? ""}
                onChange={(e) => onBibleChange({ background: e.target.value })}
                placeholder="开场前发生了什么…"
              />
            </label>
            <label className={styles.full}>
              大纲 / 节拍
              <textarea
                rows={6}
                value={bible.outline ?? ""}
                onChange={(e) => onBibleChange({ outline: e.target.value })}
                placeholder="分幕或章节节拍…"
              />
            </label>
            <label className={styles.full}>
              主题 / 基调 / 禁忌
              <textarea
                rows={3}
                value={bible.themes ?? ""}
                onChange={(e) => onBibleChange({ themes: e.target.value })}
              />
            </label>
            <label className={styles.full}>
              其他备忘
              <textarea
                rows={3}
                value={bible.notes ?? ""}
                onChange={(e) => onBibleChange({ notes: e.target.value })}
              />
            </label>
          </div>
          <ConstraintAuditCard
            bible={bible}
            loreEntries={loreEntries}
            hasStyleSamples={hasStyleSamples}
          />
        </section>
      )}
      {worldSub === "lore" && (
        <section className={styles.panel} style={{ padding: 0 }}>
          <LorePanel projectId={projectId} />
        </section>
      )}
      {worldSub === "entries" && (
        <section className={styles.panel} style={{ padding: 0 }}>
          <LoreEntriesPanel
            entries={loreEntries}
            onChange={onLoreEntriesChange}
            projectId={projectId}
            linkOptions={loreLinkOptions}
          />
        </section>
      )}
    </>
  );
}
