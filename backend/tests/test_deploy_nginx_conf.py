"""nginx / compose 配置守卫：**生产配置不许退步**，且几份拷贝不许飘开。

为什么专门一个文件：
1. 线上出过一次 413——背景图是以 base64 data URL 存进设置 JSON 的，而 nginx 少了
   `client_max_body_size` 就是默认 1m，稍大的图直接被 nginx 拦掉（连后端都到不了）。
2. 更早就出过一次白屏——`/assets/` 带内容哈希可以长缓存，但 **index.html / sw.js 必须
   每次校验**，否则浏览器拿旧 HTML 去要已经不存在的 chunk。
3. `Permissions-Policy` 写成 `microphone=()` 等于对所有用户禁用麦克风（语音输入失效）；
   CSP 少了 `media-src`/`worker-src` 的 `blob:` 会挡掉 blob 音频与 Worker。
   这两条**线上那份是对的、仓库模板曾经是错的**，靠"两边同步"的口头约定没能守住。
4. `deploy/setup_server.sh` 曾经复制 `frontend/nginx.conf`（本地试用的最小配置：只 listen 80、
   没有上传上限、没有缓存策略），于是新装的服务器会把这几个坑再踩一遍；
   而 `deploy/docker-compose.yml` 也少了 `443` 与 `./certs` 挂载——照着它装的新机器
   **nginx 会因为找不到证书直接起不来**。

## 这个文件能做什么、做不到什么（重要）

**能**：把"生产配置必须有哪些指令""几份拷贝共有的部分必须一致""装机与 compose 必须带上
443/certs/上传上限"钉成断言，谁改动导致退步都会红。

**做不到**：unit test 看不到服务器。**线上那份与仓库的差异**由 `deploy/push.py` 在每次部署
（或 `--check`）时比对，打印 `NGINX OK / NGINX DRIFT`——那才是唯一能看见线上文件的地方。

## 为什么有些用例会 skip

`deploy/` 整个目录**不在版本控制里**（根 `.gitignore` 第 51 行是 `deploy/`，把第 45/46 行
更细的规则一起吞了；`git ls-files deploy/` 为空）。所以新克隆与 CI 上不存在那些文件，
依赖它们的用例会 skip，只在维护者机器上跑。唯一**始终**能跑的是 `frontend/nginx.conf`
（它是版本控制的，且是镜像内自带的默认配置）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
PROD = REPO / "deploy" / "nginx.conf"
TRIAL = REPO / "frontend" / "nginx.conf"
SETUP = REPO / "deploy" / "setup_server.sh"
COMPOSE = REPO / "deploy" / "docker-compose.yml"

#: deploy/ 不在版本控制里 → 新克隆/CI 上没有这些文件，相关用例跳过（见模块 docstring）。
needs_deploy = pytest.mark.skipif(
    not PROD.exists() or not SETUP.exists() or not COMPOSE.exists(),
    reason="deploy/ 不在版本控制里（.gitignore 的 deploy/），只在维护者机器上有",
)


def _read(path: Path) -> str:
    assert path.exists(), f"找不到 {path}"
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


@needs_deploy
def test_prod_config_listens_on_443_and_redirects_http():
    text = _read(PROD)
    assert "listen 443 ssl;" in text, "生产必须开 443"
    assert "listen 80;" in text and "return 301 https://$host$request_uri;" in text, (
        "80 必须 301 到 https"
    )
    assert "ssl_certificate " in text and "ssl_certificate_key " in text


@needs_deploy
def test_prod_config_normalizes_www_to_apex():
    """www 与主域是两个 origin：cookie / localStorage / Service Worker 都按 host 隔离，
    不归一就会出现"在 www 登录、到主域显示未登录"。"""
    text = _read(PROD)
    assert "if ($host = www." in text and "return 301 https://" in text


@needs_deploy
def test_prod_config_sets_upload_limit():
    """少了它 = nginx 默认 1m：背景图（base64 data URL）稍大就 413。"""
    text = _read(PROD)
    assert re.search(r"client_max_body_size\s+3m;", text), (
        "生产配置必须显式给上传上限（线上 413 就是因为这个）"
    )


@needs_deploy
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


@needs_deploy
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


@needs_deploy
def test_permissions_policy_keeps_microphone_for_self():
    """`microphone=()` 是对所有人禁用——语音输入（Web Speech API）会直接不能录。"""
    perms = _permissions(_read(PROD))
    assert "microphone=(self)" in perms, (
        "microphone 必须放行 self；写成 () 会禁掉语音输入（仓库模板曾经就是错的）"
    )
    assert "camera=()" in perms and "geolocation=()" in perms, "相机与定位应保持关闭"


@needs_deploy
def test_gzip_on_and_never_compresses_sse():
    """text/event-stream 被压缩后 nginx 会缓冲，Agent / 管线进度就不再实时到达。"""
    text = _read(PROD)
    assert re.search(r"^\s*gzip on;", text, re.M), "nginx 默认 gzip off，必须显式开"
    types = _gzip_types(text)
    assert "application/json" in types, "设置 / 工程数据是 JSON，必须压缩"
    assert "text/event-stream" not in types, "不能压缩 SSE（会被缓冲，事件不再实时）"


@needs_deploy
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


@needs_deploy
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


@needs_deploy
def test_prod_config_keeps_media_src_for_music_and_voice():
    """CSP 里的 media-src 放开 blob: 是为了 blob 音频；这条与"语音/音乐能出声"绑定。"""
    csp = _csp(_read(PROD))
    assert "media-src" in csp and "blob:" in csp


# ---- 两份仓库配置不许飘开（frontend/nginx.conf 的注释就要求"两边同步"） -------


def test_trial_config_also_has_an_upload_limit():
    """本地试用的那份也得上限，否则本地导入稍大的图同样 413，排查半天以为是后端。"""
    assert re.search(r"client_max_body_size\s+3m;", _read(TRIAL)), (
        "frontend/nginx.conf（本地试用）也要 client_max_body_size"
    )


def test_trial_config_still_refuses_to_compress_sse():
    types = _gzip_types(_read(TRIAL))
    assert "text/event-stream" not in types


@needs_deploy
def test_shared_security_headers_do_not_drift_between_the_two_configs():
    """两份配置共有的安全头必须逐字一致——"两边同步"不能只靠注释里的一句话。"""
    prod, trial = _read(PROD), _read(TRIAL)
    assert _csp(prod) == _csp(trial), "两份配置的 CSP 已经不一致了"
    assert _permissions(prod) == _permissions(trial), "两份配置的 Permissions-Policy 不一致"
    assert _gzip_types(prod) == _gzip_types(trial), "两份配置的 gzip_types 不一致"


# ---- 装机路径与 compose 必须带上 443 / certs / 上传上限 ------------------------


@needs_deploy
def test_setup_script_installs_the_production_config():
    """装机脚本曾经复制 frontend/nginx.conf（最小试用版），于是新机器缺上传上限、
    缺 TLS/www 归一、缺缓存策略——线上踩过的坑会在新环境原样复现。

    只检查**代码行**：注释与提示语里可以（也应该）说明为什么不用 frontend/nginx.conf；
    真正要拦的是"从它 cp 过去"这个动作。
    """
    script = _code(_read(SETUP))
    assert '"$SCRIPT_DIR/nginx.conf"' in script, "装机应复制 deploy/nginx.conf"
    offenders = [
        line for line in script.splitlines() if "cp " in line and "frontend/nginx.conf" in line
    ]
    assert not offenders, (
        f"装机脚本不该从 frontend/nginx.conf 复制（那是本地试用配置，缺上传上限与 TLS）：{offenders}"
    )


@needs_deploy
def test_setup_script_creates_the_certs_directory():
    """compose 把 ./certs 只读挂进 nginx 的证书目录；目录不存在时 nginx 会因为找不到
    证书**直接起不来**（比缺上传上限更严重），所以装机就要建出来。"""
    script = _code(_read(SETUP))
    assert "$APP_DIR/certs" in script, "装机必须创建 $APP_DIR/certs"


@needs_deploy
def test_setup_script_tells_the_user_to_place_certificates():
    """证书文件名写死在 nginx.conf 里，装机提示必须把它讲出来，否则"装完了但起不来"。"""
    script = _read(SETUP)
    assert "vnscriptstudio.cn_bundle.crt" in script and "vnscriptstudio.cn.key" in script, (
        "装机说明要写清证书文件名（配置里就是这两个）"
    )
    assert "nginx -t" in script, "改完配置要先自检"


@needs_deploy
def test_deploy_compose_exposes_443_and_mounts_certs():
    """仓库这份 compose 曾经缺 `443:443` 与 `./certs` 挂载（只存在于服务器那份上），
    照着它装的新机器不会开 443、也没有证书目录。"""
    text = _code(_read(COMPOSE))
    assert '"443:443"' in text, "web 服务必须发布 443"
    assert "./certs:/etc/nginx/certs:ro" in text, "必须把 ./certs 挂进容器"
    assert "./nginx.conf:/etc/nginx/conf.d/default.conf:ro" in text
    assert "./frontend/dist:/usr/share/nginx/html" in text
