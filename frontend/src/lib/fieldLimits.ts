/**
 * 界面上的字段长度上限 —— **与后端一一对应**（`backend/app/core/field_limits.py`）。
 *
 * 为什么要有：`projects.title` / `projects.genre` 在数据库里是有长度的（255 / 128）。
 * 界面输入框没有上限时，用户贴一段长文本进去，保存会在数据库层被拒；
 * 以前甚至变成 500（界面只有一句"保存失败"），**从那以后每次自动保存都继续失败**
 * —— 一个标签字段就能把整部作品卡住（2026-09-26 线上实测，15 次连续失败）。
 *
 * 现在的三道门：
 * 1. 这里 → 输入框 `maxLength`（打不进去，最省事）；
 * 2. 超长的**存量**值（例如上次粘贴留下的）→ `overLimitHint` 就地提醒，不用等一次失败的保存；
 * 3. 后端 → 400 + 说清是哪一项、超了多少（万一前两道被绕过，也不会变成 500）。
 *
 * 数字改了要两边一起改：`backend/tests/test_field_limits.py` 会核对两份一致。
 */

export const TITLE_MAX = 255;
export const GENRE_MAX = 128;

/** 已超出上限？（边界包含：正好等于上限是允许的） */
export function isOverLimit(value: string, max: number): boolean {
  return value.length > max;
}

/**
 * 超长时就地提醒的那句话：说清现在多少字、上限多少、要删多少。
 * 只说"太长了"等于没说——用户还是得自己数。
 */
export function overLimitHint(label: string, value: string, max: number): string {
  const over = value.length - max;
  return `${label}超出上限：现在 ${value.length} 字，最多 ${max} 字（请删掉 ${over} 字）——超长时保存会被服务端拒绝。`;
}
