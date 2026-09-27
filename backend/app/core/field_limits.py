"""作品级字段的长度上限：一处定义，写路径、前端提示与测试共用。

**为什么要有这个模块（线上实测的坑，2026-09-26）**：

`projects.title` 是 `varchar(255)`、`projects.genre` 是 `varchar(128)`，
但请求体与界面输入框都没有上限。用户在「视图 → 设定 → 类型 / 题材」里贴了一段长文本后：

- Postgres 报 `value too long for type character varying(128)`；
- SQLAlchemy 抛 DataError，FastAPI 兜底成 **500**（响应体是 Starlette 那句
  `Internal Server Error`，没有任何线索）；
- 界面只显示「保存失败」，**从那以后每一次自动保存都继续失败**——
  一个标签字段就能把整部作品卡住（实测那个项目连续 15 次保存全 500，
  `updated_at` 冻在最后一次成功的时刻，之后的改动一个字都没落盘）。

所以这里的规矩是：
1. 上限**只在这里写一次**（前端 `frontend/src/lib/fieldLimits.ts` 与之对应，
   `tests/test_field_limits.py` 会核对两边一致 + 与数据库列宽一致）；
2. 用户直连的写路径（PUT / PATCH / 新建）超长 → **400 + 说清是哪个字段、超了多少**，
   而不是 500；
3. 内部产生方（Agent 改写、导入、模板、缓存着的旧前端）不该因为一个标签超长
   就让整次保存失败 → 见 `services/projects.py::sync_row_from_vn` 的最后一道夹取。
"""

from __future__ import annotations

# 与 app/models/tables.py 中 Project.title / Project.genre 的列宽一致
TITLE_MAX = 255
GENRE_MAX = 128

# 界面上的字段名（错误信息里要用人话，不能写 title / genre）
TITLE_LABEL = "作品标题"
GENRE_LABEL = "类型 / 题材"


def _too_long(label: str, value: str, limit: int) -> str:
    return (
        f"{label}最多 {limit} 字（现在 {len(value)} 字），这次保存被拒绝——"
        f"请精简到 {limit} 字以内再保存。"
    )


def limit_error(*, title: str | None = None, genre: str | None = None) -> str | None:
    """返回一句给人看的错误；没问题就返回 None。

    **纯函数**：不碰数据库、不抛 HTTPException，所以能离线测，
    也能被 API 层之外的地方复用（例如导入前的预检）。
    """
    if isinstance(title, str) and len(title) > TITLE_MAX:
        return _too_long(TITLE_LABEL, title, TITLE_MAX)
    if isinstance(genre, str) and len(genre) > GENRE_MAX:
        return _too_long(GENRE_LABEL, genre, GENRE_MAX)
    return None


def clamp(value: str | None, limit: int) -> str | None:
    """截到上限（只给"内部产生方"的最后一道网用，见模块 docstring 第 3 条）。"""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit]
    return value
