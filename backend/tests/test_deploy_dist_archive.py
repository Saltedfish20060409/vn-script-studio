"""部署产物：`dist.tar.gz` 的**包内布局**必须与解包命令对得上。

## 这条测试是为哪个 bug 写的（2026-10）

手工部署时发现 `deploy/deploy.py` 把前端产物按 `frontend/dist` 打包（成员形如
`frontend/dist/index.html`），解包却写 `--strip-components=1`——那会解成
**`frontend/dist/dist/index.html`**。而 nginx 容器挂的正是 `frontend/dist`
（`ops/docker-compose.server.yml` 里那条 bind），于是部署完是**整站 404**：
部署输出一路绿灯，站却打不开。

同一份产物在 `deploy/push.py` 里写的是 `--strip-components=2`（对的）。所以这不是"哪个数字写错了"，
而是**打包方与解包方各写一个数字**：谁都不会因为另一个改了而报错。修法是把层数做成
`pack.DIST_STRIP_COMPONENTS`（由 `DIST_ARCNAME` 推导）这一个真源，两个消费方都引用它。

## 为什么断言写成这两层

1. **行为**：真的打一次包，把成员按声明的层数剥掉之后，必须正好落回 dist 根
   （`index.html` / `assets/…`）。这一条不依赖任何写死的数字——改了打包方式它会跟着变。
2. **来源**：两个解包脚本都必须引用那个常量，不许再出现写死的 `--strip-components=<数字>`。

## 跑不跑得起来

`deploy/` 是**不入库的私有运维脚本**（`.gitignore` 有意为之），所以没有该目录的环境
（CI）会 skip —— 这与 `test_deploy_nginx_conf.py` 的约定一致。
守卫的价值在这里：**测试本身在库里**，改了打包方式却忘了改解包命令时，维护者机器上会红。
"""
from __future__ import annotations

import importlib
import re
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
DEPLOY_DIR = REPO / "deploy"
PACK = DEPLOY_DIR / "pack.py"
CONSUMERS = ("deploy.py", "push.py")

needs_deploy = pytest.mark.skipif(
    not (PACK.exists() and all((DEPLOY_DIR / n).exists() for n in CONSUMERS)),
    reason="deploy/ 是不入库的私有运维脚本，只在维护者机器上",
)


def _pack():
    """导入 `deploy.pack`（它只依赖 os/tarfile，没有 paramiko，所以能在测试里直接跑）。"""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    return importlib.import_module("deploy.pack")


# ---- 1. 行为：剥掉之后正好落回 dist 根 -----------------------------------------


@needs_deploy
def test_members_land_at_the_dist_root_after_stripping(tmp_path, monkeypatch):
    pack = _pack()
    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("x", encoding="utf-8")
    monkeypatch.setattr(pack, "ROOT", str(tmp_path))

    out = tmp_path / "dist.tar.gz"
    pack._dist_tar(str(out))

    with tarfile.open(out, "r:gz") as tf:
        # 只取**普通文件**：目录也会作为成员出现，而"落地到哪"说的是文件
        names = [m.name for m in tf.getmembers() if m.isfile()]
    assert names, "包里不该是空的"
    prefix = pack.DIST_ARCNAME + "/"
    assert all(n.startswith(prefix) for n in names), names

    stripped = sorted(
        "/".join(n.split("/")[pack.DIST_STRIP_COMPONENTS :]) for n in names
    )
    # 剥掉声明的层数之后必须**正好**是 dist 里的相对路径，不能多一层也不能少一层
    assert stripped == ["assets/index-abc.js", "index.html"], stripped


@needs_deploy
def test_strip_count_is_derived_from_the_arcname():
    """层数必须是推导出来的：写死就等于又开了第二个真源。"""
    pack = _pack()
    assert pack.DIST_ARCNAME == "frontend/dist"
    assert pack.DIST_STRIP_COMPONENTS == len(pack.DIST_ARCNAME.split("/")) == 2


# ---- 2. 来源：消费方不许再写死数字 ---------------------------------------------


def _code(path: Path) -> str:
    """剥掉 `#` 注释行后再断言。

    与 `test_deploy_nginx_conf._code` 同一个理由：这些脚本的注释里**会引用**那些值本身
    （比如"这里曾经写死 1"、"旧机 IP 已作废"），不剥的话会把说明文字当违规。
    """
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


@needs_deploy
@pytest.mark.parametrize("name", CONSUMERS)
def test_extract_command_uses_the_shared_constant(name):
    src = _code(DEPLOY_DIR / name)
    assert "DIST_STRIP_COMPONENTS" in src, f"{name} 解包 dist 时应引用常量"
    assert not re.search(r"--strip-components=\d", src), (
        f"{name} 里还留着写死的 --strip-components 数字——"
        "那正是 2026-10 那次「部署绿灯、整站 404」的成因"
    )


@needs_deploy
@pytest.mark.parametrize("name", ("deploy.py", "push.py"))
def test_arcname_is_not_retyped_in_the_consumers(name):
    src = _code(DEPLOY_DIR / name)
    assert 'arcname="frontend/dist"' not in src, f"{name} 自己又抄了一份 arcname"


@needs_deploy
def test_deploy_script_does_not_carry_the_retired_host():
    """旧生产机 IP 已作废（`remote.py` 里写着它的来龙去脉）。

    它曾经作为 `main()` 里一个**从没被用过**的局部默认值躺着——功能上无害，
    但足以让读代码的人以为"这份脚本部的是旧机"。真源只有 `remote.connect()` 一处。
    """
    assert "43.156.52.101" not in _code(DEPLOY_DIR / "deploy.py")
