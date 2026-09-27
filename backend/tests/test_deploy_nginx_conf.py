"""nginx / compose 配置守卫：**生产契约不许退步**，且几份拷贝不许飘开。

为什么专门一个文件：
1. 线上出过一次 413——背景图是以 base64 data URL 存进设置 JSON 的，而 nginx 少了
   `client_max_body_size` 就是默认 1m，稍大的图直接被 nginx 拦掉（连后端都到不了）。
2. 更早就出过一次白屏——`/assets/` 带内容哈希可以长缓存，但 **index.html / sw.js 必须
   每次校验**，否则浏览器拿旧 HTML 去要已经不存在的 chunk。
3. `Permissions-Policy` 写成 `microphone=()` 等于对所有用户禁用麦克风（语音输入失效）；
   CSP 少了 `media-src`/`worker-src` 的 `blob:` 会挡掉 blob 音频与 Worker。
   这两条**线上那份是对的、仓库模板曾经是错的**，靠"两边同步"的口头约定没能守住。
4. `deploy/setup_server.sh` 曾经复制 `frontend/nginx.conf`（镜像内自带的默认配置：只 listen 80、
   没有上传上限、没有缓存策略），于是新装的服务器会把这几个坑再踩一遍；
   而 compose 也少了 `443` 与 `./certs` 挂载——照着装的新机器**nginx 会因为找不到证书
   直接起不来**。

## 文件布局（这份测试的路径就是这份布局的守卫）

| 文件 | 角色 | 入库 |
|---|---|---|
| `ops/nginx.conf` | **生产 nginx 契约**（TLS / 443 / 安全头 / 缓存 / 反代） | ✅ 已跟踪 |
| `ops/docker-compose.server.yml` | **生产 compose 契约**（含 443 与 certs 挂载） | ✅ 已跟踪 |
| `frontend/nginx.conf` | 镜像内自带的默认配置（本地试用 + 无挂载时兜底） | ✅ 已跟踪 |
| `deploy/setup_server.sh`、`deploy/push.py` … | 私有运维脚本 | ❌ 不入库（`.gitignore` 有意为之） |

前两份原先只存在于维护者机器（`deploy/`）与服务器上，于是双双漂开。放进 `ops/` 之后：
单一真源、漂移结构性消失、这份守卫在**任何环境**都能跑。第三份是本地试用配置，它不得与
生产配置在共有的安全头上分叉。

## 做不到什么（写清楚免得误会）

unit test 看不到服务器。**线上那份与 `ops/` 的差异**由 `deploy/push.py` 在每次部署
（或 `--check`）时比对，打印 `DRIFT OK / DRIFT!!`——那才是唯一能看见线上文件的地方。
依赖 `deploy/`（不入库）的那几条用例在没有该目录的环境会 **skip**。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
#: 生产契约（已入库）——下面绝大多数断言只看它们，所以到处都能跑
PROD = REPO / "ops" / "nginx.conf"
COMPOSE = REPO / "ops" / "docker-compose.server.yml"
#: 镜像内自带的默认配置（也是本地 docker compose 试用用的那份）
TRIAL = REPO / "frontend" / "nginx.conf"
#: 私有运维脚本：不入库，只能在这台维护者机器上看到
SETUP = REPO / "deploy" / "setup_server.sh"
PUSH = REPO / "deploy" / "push.py"

needs_setup = pytest.mark.skipif(
    not SETUP.exists(),
    reason="deploy/setup_server.sh 是私有运维脚本（不入库），只在维护者机器上",
)
needs_push = pytest.mark.skipif(
    not PUSH.exists(),
    reason="deploy/push.py 是私有运维脚本（不入库），只在维护者机器上",
)


def _read(path: Path) -> str:
    assert path.exists(), f"找不到 {path}（这份应当已入库）"
    return path.read_text(encoding="utf-8")


def _code(text: str) -> str:
    """剥掉 `#` 注释行。

    必须这么做：这些配置的注释里**会引用**指令本身（例如 frontend/nginx.conf 的注释写着
    "gzip_types 里不能加 text/event-stream"），不剥的话正则第一次命中的是注释，
    会把"注释里提到"误判成"配置里有"。
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _csp(text: str) -> str:
    m = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]+)"', _code(text))
    assert m, "没有找到 Content-Security-Policy"
    return m.group(1)


def _permissions(text: str) -> str:
    m = re.search(r'add_header\s+Permissions-Policy\s+"([^"]+)"', _code(text))
    assert m, "没有找到 Permissions-Policy"
    return m.group(1)


def _gzip_types(text: str) -> set[str]:
    """按行首的 `gzip_types` 取列表（注释已剥掉，不会再命中注释里的提法）。"""
    m = re.search(r"^\s*gzip_types\s+([^;]+);", _code(text), re.M)
    assert m, "没有找到 gzip_types"
    return set(m.group(1).split())


def _header_value(text: str, name: str) -> str | None:
    """取某个 `add_header` 的整条值。

    不能写成 `[^;]+`——CSP 与 HSTS 的**值里本身就有分号**
    （`default-src 'self'; script-src ...`、`max-age=31536000; includeSubDomains`），
    那样会在分号处截断，连带 `always` 都匹配不到。
    """
    m = re.search(rf'add_header\s+{name}\s+"([^"]*)"([^;]*);', _code(text))
    if not m:
        m = re.search(rf"add_header\s+{name}\s+([^;]*);", _code(text))
    return m.group(0) if m else None


# ---- 生产模板必须有哪些指令（每条都写清为什么，退步就会红） ------------------


def test_prod_config_listens_on_443_and_redirects_http():
    text = _read(PROD)
    assert "listen 443 ssl;" in text, "生产必须开 443"
    assert "listen 80;" in text and "return 301 https://$host$request_uri;" in text, (
        "80 必须 301 到 https"
    )
    assert "ssl_certificate " in text and "ssl_certificate_key " in text


def test_prod_config_normalizes_www_to_apex():
    """www 与主域是两个 origin：cookie / localStorage / Service Worker 都按 host 隔离，
    不归一就会出现"在 www 登录、到主域显示未登录"。"""
    text = _read(PROD)
    assert "if ($host = www." in text and "return 301 https://" in text


def test_prod_config_sets_upload_limit():
    """少了它 = nginx 默认 1m：背景图（base64 data URL）稍大就 413。"""
    assert re.search(r"client_max_body_size\s+3m;", _read(PROD)), (
        "生产配置必须显式给上传上限（线上 413 就是因为这个）"
    )


def test_prod_config_keeps_security_headers_with_always():
    """`always` 保证 4xx/5xx 错误页也带这些头。"""
    text = _read(PROD)
    for name in (
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "Permissions-Policy",
    ):
        got = _header_value(text, name)
        assert got, f"缺少 {name}"
        assert "always" in got, f"{name} 必须带 always（错误页也要有）：{got}"


def test_csp_allows_what_the_app_actually_needs():
    """CSP 的每一项都对应一个真实需求，少一项就是线上功能直接坏掉。"""
    csp = _csp(_read(PROD))
    # 背景图是 data URL
    assert "img-src 'self' data:" in csp, "img-src 必须放行 data:（背景图是 data URL）"
    # CSS Modules 注入 style 标签
    assert "style-src 'self' 'unsafe-inline'" in csp, (
        "style-src 需要 'unsafe-inline'（CSS Modules 注入 style）"
    )
    # blob 音频（音乐条 / 语音）与 Worker
    assert "media-src 'self' https: blob:" in csp, "media-src 必须含 blob:（blob 音频播放）"
    assert "worker-src 'self' blob:" in csp, "worker-src 必须含 blob:（Worker）"
    assert "default-src 'self'" in csp


def test_permissions_policy_keeps_microphone_for_self():
    """`microphone=()` 是对所有人禁用——语音输入（Web Speech API）会直接不能录。"""
    perms = _permissions(_read(PROD))
    assert "microphone=(self)" in perms, (
        "microphone 必须放行 self；写成 () 会禁掉语音输入（仓库模板曾经就是错的）"
    )
    assert "camera=()" in perms and "geolocation=()" in perms, "相机与定位应保持关闭"


def test_gzip_on_and_never_compresses_sse():
    """text/event-stream 被压缩后 nginx 会缓冲，Agent / 管线进度就不再实时到达。"""
    text = _read(PROD)
    assert re.search(r"^\s*gzip on;", text, re.M), "nginx 默认 gzip off，必须显式开"
    types = _gzip_types(text)
    assert "application/json" in types, "设置 / 工程数据是 JSON，必须压缩"
    assert "text/event-stream" not in types, "不能压缩 SSE（会被缓冲，事件不再实时）"


def test_prod_config_keeps_cache_strategy():
    """带哈希的产物长缓存；index.html / sw.js 必须每次校验，否则旧 HTML 去要已删除的
    chunk → 白屏（线上报过一次）。"""
    text = _read(PROD)
    assets = re.search(r"location /assets/ \{([^}]*)\}", text)
    assert assets and "expires 1y;" in assets.group(1)
    for path in ("/index.html", "/sw.js"):
        block = re.search(rf"location = {re.escape(path)} \{{([^}}]*)\}}", text)
        assert block, f"缺少 {path} 的 location"
        assert "expires -1;" in block.group(1), f"{path} 必须不走缓存"
    # SPA fallback 也是入口，no-cache 要在这里再写一遍
    spa = re.search(r"location @spa \{([^}]*)\}", text)
    assert spa and "expires -1;" in spa.group(1), "SPA fallback 入口也必须 no-cache"


def test_prod_config_proxies_api_with_sse_friendly_settings():
    text = _read(PROD)
    api = re.search(r"location /api/ \{([^}]*)\}", text)
    assert api, "缺少 /api/ 反代"
    body = api.group(1)
    assert "proxy_buffering off;" in body, "SSE 必须关缓冲"
    assert "proxy_read_timeout 3600s;" in body, "Agent 长任务需要长读超时"
    # 覆盖而非追加 XFF：否则客户端伪造的 X-Forwarded-For 能绕过后端限流
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in body, (
        "X-Forwarded-For 必须覆盖（追加会让客户端伪造的值传到后端，绕开限流）"
    )
    assert re.search(r"location = /health \{\s*proxy_pass http://api:8000/health;", text), (
        "缺少 /health 直通（部署校验用它）"
    )


# ---- 两份仓库配置不许飘开（frontend/nginx.conf 的注释就要求"两边同步"） -------


def test_trial_config_also_has_an_upload_limit():
    """本地试用的那份也得上限，否则本地导入稍大的图同样 413，排查半天以为是后端。"""
    assert re.search(r"client_max_body_size\s+3m;", _read(TRIAL)), (
        "frontend/nginx.conf（本地试用 / 镜像内默认）也要 client_max_body_size"
    )


def test_trial_config_still_refuses_to_compress_sse():
    assert "text/event-stream" not in _gzip_types(_read(TRIAL))


def test_shared_security_headers_do_not_drift_between_the_two_configs():
    """两份配置共有的安全头必须逐字一致——"两边同步"不能只靠注释里的一句话。"""
    prod, trial = _read(PROD), _read(TRIAL)
    assert _csp(prod) == _csp(trial), "两份配置的 CSP 已经不一致了"
    assert _permissions(prod) == _permissions(trial), "两份配置的 Permissions-Policy 不一致"
    assert _gzip_types(prod) == _gzip_types(trial), "两份配置的 gzip_types 不一致"


# ---- 生产 compose 必须带上 443 / certs --------------------------------------


def test_server_compose_exposes_443_and_mounts_certs():
    """这份 compose 曾经缺 `443:443` 与 `./certs` 挂载（只存在于服务器那份上），
    照着它装的新机器不会开 443、也没有证书目录——而 nginx 配置里写死了证书路径，
    结果是 **nginx 直接起不来**。"""
    text = _code(_read(COMPOSE))
    assert '"443:443"' in text, "web 服务必须发布 443"
    assert "./certs:/etc/nginx/certs:ro" in text, "必须把 ./certs 挂进容器"
    assert "./nginx.conf:/etc/nginx/conf.d/default.conf:ro" in text
    assert "./frontend/dist:/usr/share/nginx/html" in text


def test_server_compose_keeps_nginx_pinned_to_a_digest():
    """nginx 镜像必须钉 digest（可复现部署；:latest 会无预警漂移）。"""
    text = _code(_read(COMPOSE))
    assert re.search(r"image:\s*nginx:[\w.\-]+@sha256:[0-9a-f]{64}", text), (
        "nginx 镜像应写 `nginx:<tag>@sha256:<digest>`"
    )


# ---- 装机脚本（私有，不入库；有它才跑） --------------------------------------


@needs_setup
def test_setup_script_installs_the_production_config_from_ops():
    """装机脚本曾经复制 frontend/nginx.conf（默认配置），于是新机器缺上传上限、缺 TLS。

    只检查**代码行**：注释与提示语里可以（也应该）说明为什么不用 frontend/nginx.conf；
    真正要拦的是"从它 cp 过去"这个动作。
    """
    script = _code(_read(SETUP))
    assert "$OPS_DIR/nginx.conf" in script, "装机应从 ops/nginx.conf 复制（生产真源）"
    assert "$OPS_DIR/docker-compose.server.yml" in script, "compose 也应来自 ops/"
    offenders = [
        line for line in script.splitlines() if "cp " in line and "frontend/nginx.conf" in line
    ]
    assert not offenders, (
        f"装机脚本不该从 frontend/nginx.conf 复制（那是默认/试用配置，缺上传上限与 TLS）：{offenders}"
    )


@needs_setup
def test_setup_script_creates_the_certs_directory():
    """compose 把 ./certs 只读挂进 nginx 的证书目录；目录不存在时 nginx 会因为找不到
    证书**直接起不来**（比缺上传上限更严重），所以装机就要建出来。"""
    script = _code(_read(SETUP))
    assert "$APP_DIR/certs" in script, "装机必须创建 $APP_DIR/certs"


@needs_setup
def test_setup_script_tells_the_user_to_place_certificates():
    """证书文件名写死在 nginx.conf 里，装机提示必须把它讲出来，否则"装完了但起不来"。"""
    script = _read(SETUP)
    assert "vnscriptstudio.cn_bundle.crt" in script and "vnscriptstudio.cn.key" in script, (
        "装机说明要写清证书文件名（配置里就是这两个）"
    )
    assert "nginx -t" in script, "改完配置要先自检"


# ---- 私有部署脚本自身的守卫（有它才跑） --------------------------------------


@needs_push
def test_push_compares_drift_against_both_ops_files():
    """漂移检查必须同时盯着 nginx.conf 与 server compose——少一个就等于没查。"""
    src = _read(PUSH)
    # 注意要截到**外层**元组的收尾（`\n)`），按第一个 `)` 截只会拿到第一条
    block = src.split("DRIFT_FILES = (", 1)[1].split("\n)", 1)[0]
    assert "ops/nginx.conf" in block, "漂移检查没有比对 ops/nginx.conf"
    assert "ops/docker-compose.server.yml" in block, "漂移检查没有比对 ops/docker-compose.server.yml"


@needs_push
def test_push_refuses_to_deploy_a_stale_frontend_artifact():
    """`--frontend` 发的是 `deploy/artifacts/dist.tar.gz` 这个**打包件**，它不会自己重新打包。

    2026-09-27 踩过一次：改完前端忘了 `pack.py`，于是**静默发了上一版**，而部署输出一路
    `HASH OK`（它比的是"服务器上的 dist"与"公网"，两边都是同一份旧的，当然一致）。
    所以 push.py 必须在前端分支里先校验打包件是否过期。
    """
    src = _read(PUSH)
    assert "def _assert_dist_tar_is_fresh" in src, "缺少打包件过期检查函数"
    assert re.search(r"_assert_dist_tar_is_fresh\(dist_tar\)", src), (
        "前端分支没有调用打包件过期检查——会回到'静默发上一版'"
    )
    assert "pack.py" in src, "提示里要写清先跑 deploy/pack.py"
