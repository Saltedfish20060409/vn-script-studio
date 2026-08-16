import { uid } from "../lib/vnLocal";
import type { Character, GameVariable, SpriteDef, VnProject } from "../types/vn";
import styles from "./StudioApp.module.css";

type Props = {
  project: VnProject;
  onChange: (updater: (p: VnProject) => VnProject) => void;
  sub: "variables" | "sprites";
  onSub: (s: "variables" | "sprites") => void;
};

export function SystemPanel({ project, onChange, sub, onSub }: Props) {
  const variables = project.variables ?? [];
  const sprites = project.sprites ?? [];

  function addVar() {
    onChange((p) => ({
      ...p,
      variables: [
        ...(p.variables ?? []),
        {
          id: uid("var"),
          name: "好感度",
          key: `affection_${(p.variables ?? []).length + 1}`,
          type: "number",
          value: 0,
          note: "",
        } satisfies GameVariable,
      ],
    }));
  }

  function patchVar(id: string, patch: Partial<GameVariable>) {
    onChange((p) => ({
      ...p,
      variables: (p.variables ?? []).map((v) => (v.id === id ? { ...v, ...patch } : v)),
    }));
  }

  function addSprite() {
    onChange((p) => ({
      ...p,
      sprites: [
        ...(p.sprites ?? []),
        {
          id: uid("spr"),
          name: "新立绘",
          imageTag: "char_new",
          expressions: [
            { id: uid("ex"), name: "默认", tag: "normal" },
            { id: uid("ex"), name: "微笑", tag: "smile" },
            { id: uid("ex"), name: "害羞", tag: "shy" },
          ],
        } satisfies SpriteDef,
      ],
    }));
  }

  function patchSprite(id: string, patch: Partial<SpriteDef>) {
    onChange((p) => ({
      ...p,
      sprites: (p.sprites ?? []).map((s) => (s.id === id ? { ...s, ...patch } : s)),
    }));
  }

  return (
    <section className={styles.panel}>
      <div className={styles.subNav}>
        <button
          type="button"
          className={sub === "variables" ? styles.subActive : styles.subTab}
          onClick={() => onSub("variables")}
        >
          变量 / 好感度
        </button>
        <button
          type="button"
          className={sub === "sprites" ? styles.subActive : styles.subTab}
          onClick={() => onSub("sprites")}
        >
          立绘 / 表情槽
        </button>
      </div>

      {sub === "variables" && (
        <>
          <div className={styles.toolbar}>
            <span>状态机变量会写入 Agent 上下文，便于按好感度写戏</span>
            <button type="button" className={styles.primary} onClick={addVar}>
              添加变量
            </button>
          </div>
          <div className={styles.charGrid}>
            {variables.map((v) => (
              <article key={v.id} className={styles.charCard}>
                <div className={styles.cardHead}>
                  <strong>{v.name || v.key}</strong>
                  <button
                    type="button"
                    className={styles.danger}
                    onClick={() =>
                      onChange((p) => ({
                        ...p,
                        variables: (p.variables ?? []).filter((x) => x.id !== v.id),
                      }))
                    }
                  >
                    删除
                  </button>
                </div>
                <label>
                  显示名
                  <input
                    value={v.name}
                    onChange={(e) => patchVar(v.id, { name: e.target.value })}
                  />
                </label>
                <label>
                  键名（Ren&apos;Py）
                  <input
                    value={v.key}
                    onChange={(e) =>
                      patchVar(v.id, {
                        key: e.target.value.replace(/[^A-Za-z0-9_]/g, ""),
                      })
                    }
                  />
                </label>
                <label>
                  类型
                  <select
                    value={v.type}
                    onChange={(e) => {
                      const type = e.target.value as GameVariable["type"];
                      const value =
                        type === "number" ? 0 : type === "bool" ? false : "";
                      patchVar(v.id, { type, value });
                    }}
                  >
                    <option value="number">数字</option>
                    <option value="bool">布尔</option>
                    <option value="string">字符串</option>
                  </select>
                </label>
                <label>
                  当前值
                  {v.type === "bool" ? (
                    <select
                      value={String(v.value)}
                      onChange={(e) =>
                        patchVar(v.id, { value: e.target.value === "true" })
                      }
                    >
                      <option value="false">false</option>
                      <option value="true">true</option>
                    </select>
                  ) : (
                    <input
                      type={v.type === "number" ? "number" : "text"}
                      value={String(v.value)}
                      onChange={(e) =>
                        patchVar(v.id, {
                          value:
                            v.type === "number"
                              ? Number(e.target.value)
                              : e.target.value,
                        })
                      }
                    />
                  )}
                </label>
                <label>
                  绑定角色（好感度）
                  <select
                    value={v.bindCharacterId ?? ""}
                    onChange={(e) =>
                      patchVar(v.id, {
                        bindCharacterId: e.target.value || undefined,
                      })
                    }
                  >
                    <option value="">无</option>
                    {project.characters.map((c: Character) => (
                      <option key={c.id} value={c.id}>
                        {c.displayName}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  备注
                  <textarea
                    rows={2}
                    value={v.note ?? ""}
                    onChange={(e) => patchVar(v.id, { note: e.target.value })}
                  />
                </label>
              </article>
            ))}
          </div>
        </>
      )}

      {sub === "sprites" && (
        <>
          <div className={styles.toolbar}>
            <span>立绘与表情槽：对白旁可标注 show 标签</span>
            <button type="button" className={styles.primary} onClick={addSprite}>
              添加立绘
            </button>
          </div>
          <div className={styles.charGrid}>
            {sprites.map((s) => (
              <article key={s.id} className={styles.charCard}>
                <div className={styles.cardHead}>
                  <strong>{s.name}</strong>
                  <button
                    type="button"
                    className={styles.danger}
                    onClick={() =>
                      onChange((p) => ({
                        ...p,
                        sprites: (p.sprites ?? []).filter((x) => x.id !== s.id),
                      }))
                    }
                  >
                    删除
                  </button>
                </div>
                <label>
                  名称
                  <input
                    value={s.name}
                    onChange={(e) => patchSprite(s.id, { name: e.target.value })}
                  />
                </label>
                <label>
                  基础 image
                  <input
                    value={s.imageTag}
                    onChange={(e) => patchSprite(s.id, { imageTag: e.target.value })}
                    placeholder="linxia"
                  />
                </label>
                <label>
                  绑定角色
                  <select
                    value={s.characterId ?? ""}
                    onChange={(e) =>
                      patchSprite(s.id, {
                        characterId: e.target.value || undefined,
                      })
                    }
                  >
                    <option value="">无</option>
                    {project.characters.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.displayName}
                      </option>
                    ))}
                  </select>
                </label>
                <p className={styles.sideLabel}>表情槽</p>
                <ul className={styles.exprList}>
                  {s.expressions.map((ex, i) => (
                    <li key={ex.id}>
                      <input
                        value={ex.name}
                        onChange={(e) => {
                          const expressions = s.expressions.map((x, j) =>
                            j === i ? { ...x, name: e.target.value } : x
                          );
                          patchSprite(s.id, { expressions });
                        }}
                        placeholder="名称"
                      />
                      <input
                        value={ex.tag}
                        onChange={(e) => {
                          const expressions = s.expressions.map((x, j) =>
                            j === i ? { ...x, tag: e.target.value } : x
                          );
                          patchSprite(s.id, { expressions });
                        }}
                        placeholder="tag"
                      />
                      <code>
                        show {s.imageTag} {ex.tag}
                      </code>
                      <button
                        type="button"
                        onClick={() =>
                          patchSprite(s.id, {
                            expressions: s.expressions.filter((_, j) => j !== i),
                          })
                        }
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  className={styles.ghost}
                  onClick={() =>
                    patchSprite(s.id, {
                      expressions: [
                        ...s.expressions,
                        { id: uid("ex"), name: "新表情", tag: "new" },
                      ],
                    })
                  }
                >
                  + 表情
                </button>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
