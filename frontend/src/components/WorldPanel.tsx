import { ColorPicker } from "./ColorPicker";
import { LorePanel } from "./LorePanel";
import type { Character, StoryBible } from "../types/vn";
import styles from "./StudioApp.module.css";

type WorldSub = "characters" | "bible" | "lore";

type Props = {
  worldSub: WorldSub;
  projectId: string;
  characters: Character[];
  logline: string;
  genre: string;
  bible: StoryBible;
  onSelectCharacters: () => void;
  onSelectBible: () => void;
  onSelectLore: () => void;
  onAddCharacter: () => void;
  onDeleteCharacter: (id: string) => void;
  onUpdateCharacter: (id: string, patch: Partial<Character>) => void;
  onLoglineChange: (value: string) => void;
  onGenreChange: (value: string) => void;
  onBibleChange: (patch: Partial<StoryBible>) => void;
};

/**
 * 设定 tab: 角色卡 / 世界观 · 大纲 / 设定卡 secondary nav plus panels.
 * Pure presentational — update/delete logic stays in StudioApp.
 */
export function WorldPanel({
  worldSub,
  projectId,
  characters,
  logline,
  genre,
  bible,
  onSelectCharacters,
  onSelectBible,
  onSelectLore,
  onAddCharacter,
  onDeleteCharacter,
  onUpdateCharacter,
  onLoglineChange,
  onGenreChange,
  onBibleChange,
}: Props) {
  return (
    <>
      <div className={styles.subNav} style={{ padding: "0.75rem 1.1rem 0" }}>
        <button
          type="button"
          className={
            worldSub === "characters" ? styles.subActive : styles.subTab
          }
          onClick={onSelectCharacters}
        >
          角色卡
        </button>
        <button
          type="button"
          className={
            worldSub === "bible" ? styles.subActive : styles.subTab
          }
          onClick={onSelectBible}
        >
          世界观 / 大纲
        </button>
        <button
          type="button"
          className={
            worldSub === "lore" ? styles.subActive : styles.subTab
          }
          onClick={onSelectLore}
        >
          设定卡
        </button>
      </div>
      {worldSub === "characters" && (
        <section className={styles.panel}>
          <div className={styles.toolbar}>
            <span>角色卡（删除不会自动改写对白）</span>
            <button
              type="button"
              className={styles.primary}
              onClick={onAddCharacter}
            >
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
                  define 名
                  <input
                    value={c.defineName}
                    onChange={(e) =>
                      onUpdateCharacter(c.id, {
                        defineName: e.target.value.replace(
                          /[^A-Za-z0-9_]/g,
                          ""
                        ),
                      })
                    }
                  />
                </label>
                <label>
                  颜色
                  <ColorPicker
                    value={c.color ?? "#6b7280"}
                    onChange={(color) =>
                      onUpdateCharacter(c.id, { color })
                    }
                  />
                </label>
                <label>
                  语气
                  <textarea
                    rows={2}
                    value={c.voice ?? ""}
                    onChange={(e) =>
                      onUpdateCharacter(c.id, { voice: e.target.value })
                    }
                  />
                </label>
                <label>
                  简介
                  <textarea
                    rows={3}
                    value={c.bio ?? ""}
                    onChange={(e) =>
                      onUpdateCharacter(c.id, { bio: e.target.value })
                    }
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
              </article>
            ))}
          </div>
        </section>
      )}
      {worldSub === "bible" && (
        <section className={styles.panel}>
          <div className={styles.toolbar}>
            <span>故事设定独立于角色卡，会进入 AI 上下文</span>
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
              <input
                value={genre}
                onChange={(e) => onGenreChange(e.target.value)}
              />
            </label>
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
                onChange={(e) =>
                  onBibleChange({ background: e.target.value })
                }
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
        </section>
      )}
      {worldSub === "lore" && (
        <section className={styles.panel} style={{ padding: 0 }}>
          <LorePanel projectId={projectId} />
        </section>
      )}
    </>
  );
}
