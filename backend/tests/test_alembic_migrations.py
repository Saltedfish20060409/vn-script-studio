"""迁移自身的守卫：revision id 长度与迁移链。

为什么值得单测（2026-09-28 线上事故）：新加一条迁移时把 revision 起成了
`0030_drop_dead_user_settings_columns`（38 字符），而 `alembic_version.version_num`
是 **varchar(32)**。于是迁移执行到"写版本号"那一步报
`StringDataRightTruncationError: value too long for type character varying(32)`，
**整个迁移事务回滚**（DDL 与版本号同事务），应用启动时 `alembic upgrade head` 又失败、
按 fail-fast 退出 → 容器进入重启循环，线上 api 直接不可用。
而起错名这件事没有任何本地信号：`alembic upgrade` 在本地库上也会一模一样地炸。

所以这里钉三条：
1. 每个 revision id ≤ 32 字符（alemibc 版本列宽度，写死在这条守卫里）；
2. 每条 down_revision 都能在文件集里找到（没有悬空父节点）；
3. **只有一个 head**（两个 head 会让 `upgrade head` 直接报错）。
"""
from __future__ import annotations

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

#: `alembic_version.version_num` 的实际列宽（见各迁移里 alembic 自己建的表）。
VERSION_NUM_MAX = 32

_REV = re.compile(r'^revision = "([^"]+)"', re.MULTILINE)
_DOWN = re.compile(r'^down_revision = (?:None|"([^"]+)")', re.MULTILINE)


def _migration_files() -> list[Path]:
    """versions/ 下**所有** .py（只排除 `__init__.py`）。

    刻意不排除下划线开头的文件：alembic 把该目录里每个 .py 都当迁移脚本加载，
    守卫漏掉哪个文件，就等于那个文件的长度问题能照样带到线上。
    """
    return [p for p in sorted(VERSIONS.glob("*.py")) if p.name != "__init__.py"]


def _migrations() -> list[tuple[Path, str, str | None]]:
    out: list[tuple[Path, str, str | None]] = []
    for path in _migration_files():
        text = path.read_text(encoding="utf-8")
        rev = _REV.search(text)
        if not rev:
            continue
        down = _DOWN.search(text)
        out.append((path, rev.group(1), down.group(1) if down else None))
    return out


def test_every_migration_file_declares_a_revision():
    """读不出 revision 的文件不能被静默跳过——否则上面的长度守卫会漏过它。

    （调试这条时踩过：用 PowerShell 的 `Set-Content -Encoding utf8` 造测试文件会带 BOM，
    首行变成 `\\ufeffrevision = "…"`，`^revision` 就匹配不到了。）
    """
    missing = [
        p.name for p in _migration_files() if not _REV.search(p.read_text(encoding="utf-8"))
    ]
    assert not missing, f"这些迁移文件里找不到 revision 声明：{missing}"


def test_migration_revision_ids_fit_the_version_column():
    too_long = [
        (path.name, rev, len(rev))
        for path, rev, _down in _migrations()
        if len(rev) > VERSION_NUM_MAX
    ]
    assert not too_long, (
        f"revision id 超过 alembic_version.version_num 的 {VERSION_NUM_MAX} 字符宽度，"
        f"线上会在写版本号时整条迁移回滚：{too_long}"
    )


def test_migration_chain_has_no_dangling_parent_and_a_single_head():
    rows = _migrations()
    revisions = {rev for _p, rev, _d in rows}
    dangling = [(p.name, down) for p, _rev, down in rows if down and down not in revisions]
    assert not dangling, f"down_revision 指向了不存在的 revision：{dangling}"

    parents = {down for _p, _rev, down in rows if down}
    heads = sorted(revisions - parents)
    assert len(heads) == 1, f"迁移链必须恰好一个 head，实际 {heads}"
