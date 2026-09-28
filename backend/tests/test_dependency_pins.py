"""依赖口径的守卫：`requirements.txt` 必须**真的**是精确钉版，且不许再出现装饰性 lock 文件。

为什么值得单独一个文件
----------------------
这个仓库曾经的 `requirements-lock.txt` 是个典型反例：没有任何地方消费它
（Dockerfile 与两个 CI 工作流装的都是 `requirements.txt`），也没有任何检查盯着它，
于是它停在 2026-08-24 那次冻结上并**与现实矛盾**——里面还留着已经换掉的
passlib / python-jose，却缺了替换后的 PyJWT，bcrypt 与 cryptography 的版本也对不上。
认证栈恰好就在这几条上。**一个看起来权威、实际是错的锁文件比没有更危险**，
所以它被删了（理由写在 `requirements.txt` 文件头）。

删掉之后真正要守住的是**属性**，而不是那个文件：

1. `requirements.txt` 里每个依赖都必须 `==` 钉死。它自称"精确锁定 → 可复现构建"，
   只要有一条写成 `>=` 或裸名，这句话就不成立，而且症状是"换台机器就装出别的版本"，
   极难排查。
2. 不许再出现无人消费的 lock 文件。若将来真要引入全量冻结，必须同时满足
   "Dockerfile / CI 装它" + "有一条断言它与 requirements.txt 一致"这两条，
   否则只是把上面那个坑再挖一遍。
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
REQUIREMENTS = BACKEND_ROOT / "requirements.txt"

#: `名字` 或 `名字[extra1,extra2]`，后面必须紧跟 `==版本`
_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[A-Za-z0-9,._-]+\])?"
    r"==(?P<version>[^\s;=<>!~]+)$"
)


def _dependency_lines() -> list[str]:
    out = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def test_requirements_file_exists_and_is_not_empty():
    assert REQUIREMENTS.is_file()
    assert len(_dependency_lines()) >= 10


def test_every_dependency_is_exactly_pinned():
    """核心闸：任何一条没钉死，README 里那句"精确锁定 → 可复现构建"就是假的。"""
    unpinned = [line for line in _dependency_lines() if not _PIN_RE.match(line)]
    assert unpinned == [], (
        "以下依赖没有用 `==` 精确钉版（>= / ~= / 裸名 / 区间都会导致换机器装出别的版本）："
        f"{unpinned}"
    )


def test_no_duplicate_packages():
    """同名依赖出现两次（哪怕大小写不同）时，pip 只认最后一条，前一条会静默失效。"""
    names = []
    for line in _dependency_lines():
        m = _PIN_RE.match(line)
        if m:
            names.append(m.group("name").lower().replace("_", "-"))
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"重复声明的依赖：{sorted(duplicates)}"


def test_auth_stack_is_the_maintained_pair():
    """认证栈曾经换过实现（python-jose → PyJWT、passlib → bcrypt 直用）。

    这条不是风格检查：换实现的迁移很容易只改一半——比如把依赖换了但代码里还在
    `import jose`，或者反过来。这里把**现状**钉住，逼改动者显式面对它。
    """
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert "PyJWT==" in text
    assert "bcrypt==" in text
    # 已弃用的两个必须不在（注释里提到它们的历史是允许的，这里只看依赖行）
    joined = "\n".join(_dependency_lines())
    assert "python-jose" not in joined, "python-jose 已被 PyJWT 取代，不应再作为依赖"
    assert "passlib" not in joined, "passlib 已弃用（它把 bcrypt 钉在 4.0.1），不应再作为依赖"


def test_no_unverified_lock_file():
    """不许再出现"没人装、没人验"的 lock 文件——那正是被删掉的那个坑。"""
    lock = BACKEND_ROOT / "requirements-lock.txt"
    if not lock.is_file():
        return
    consumers = [
        BACKEND_ROOT / "Dockerfile",
        REPO_ROOT / ".github" / "workflows" / "ci.yml",
        REPO_ROOT / ".github" / "workflows" / "integration.yml",
        REPO_ROOT / ".github" / "workflows" / "e2e.yml",
    ]
    used = [
        p.name
        for p in consumers
        if p.is_file() and "requirements-lock" in p.read_text(encoding="utf-8")
    ]
    assert used, (
        "backend/requirements-lock.txt 又出现了，但没有任何地方安装它。"
        "无人消费的锁文件只会随时间与现实矛盾，然后误导别人——"
        "要么让 Dockerfile/CI 真的装它，要么按 requirements.txt 文件头写的方式重新引入。"
    )
