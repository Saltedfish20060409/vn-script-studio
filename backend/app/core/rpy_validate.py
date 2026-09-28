"""导出后的 .rpy 文本体检：把"能导出"和"Ren'Py 真能跑"之间的差距变成可读结论。

为什么要这一层
--------------
1. 导出器为了防注入会**安全化**作者/AI 的值（非法 label 名、非法跳转目标一律落成
   `unnamed`）。安全化本身不报错，于是产物是"能打开、跑起来崩"的脚本，
   而作者没有任何渠道知道这件事。
2. LLM 直接产出 .rpy 的那条路（``core/prose_rpy.py``）绕过了块级导出器：
   模型写的 `[变量]`、`jump 不存在的 label` 都不经过任何检查就发给前端。
3. 导出端点是 ``PlainTextResponse``：除了"文件下载了"没有任何反馈通道。

所以这里只做一件事——**对已成文的 .rpy 文本做纯函数体检**，返回结构化 findings。
**绝不改字节**：结论走独立的响应体（``GET /export/rpy/validate``）与前端提示，
作者下载到的 .rpy 必须还是同一份剧本（合法工程一个字符都不变）。

只做"文本层面确实可判"的检查
----------------------------
控制流语义（死循环、不可达 label、无后果选项）是 ``core/branch_analysis.py`` 的活：
那边有块级信息，判得比字符串扫描准得多。这里刻意不做，避免出现第二套、更差的实现。
「悬空跳转」是个例外——两边都要判，所以判定收敛到
``branch_analysis.missing_targets``（见那里的 docstring）。

**刻意不做 `{`/`}` 检查**：花括号在 Ren'Py 里既是"作者写错的东西"，也是合法的文本标签
（`{b}粗体{/b}`、`{w}`）。文本层面分不出这两者，误报会逼作者去关掉体检；
而导出器本身已经把所有花括号转义成 `{{` `}}`，那条不变式由 `tests/test_ruby_render.py` 钉住。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.branch_analysis import missing_targets
from app.core.renpy import IDENT_FALLBACK, MARKER_PREFIX

# --------------------------------------------------------------- 文本扫描规则

#: `label 名字:`（缩进与否都收：raw 块里的 label 也算"定义过"）。
_LABEL_RE = re.compile(r"^[ \t]*label[ \t]+(?P<name>[^\s:]+)[ \t]*:")

#: `jump 目标` / `call 目标`（可带 `from 捕获名`）。行内注释与其它尾随内容一律不认，
#: 宁可漏报也不要把 `call screen x` 之类误判成 label 跳转。
_TARGET_RE = re.compile(
    r"^[ \t]*(?P<kw>jump|call)[ \t]+(?P<target>[^\s:]+)"
    r"(?:[ \t]+from[ \t]+\S+)?[ \t]*$"
)

#: `jump expression "..."` / `call screen x` 里的第一个词不是 label 名。
_NON_LABEL_TARGETS = {"expression", "screen"}

#: 以这些词开头的行**不是** say 语句（它们的引号里是文件名/条件/展示对象，不是台词）。
#: 只影响"要不要检查这句话的文本"，列全一点只会漏报、不会误报。
_NON_SAY_KEYWORDS = {
    "define", "default", "label", "jump", "call", "return", "menu", "if", "elif",
    "else", "while", "for", "pass", "init", "image", "transform", "scene", "show",
    "hide", "play", "stop", "queue", "voice", "window", "with", "pause", "camera",
    "style", "screen", "translate", "layeredimage", "include", "python", "at", "on",
    "use", "tag", "behind", "layer", "predict", "renpy", "contains", "block", "text",
    "vbox", "hbox", "frame", "grid", "side", "fixed", "$",
}

#: say 语句：`"旁白"` / `lx "台词"` / `"选项"` / `"选项" if 条件:`。
_SAY_RE = re.compile(
    r'^[ \t]*(?:(?P<who>[A-Za-z_][A-Za-z0-9_]*)[ \t]+)?'
    r'"(?P<text>(?:[^"\\]|\\.)*)"'
    r"(?:[ \t]+if\b[^:]*)?[ \t]*:?[ \t]*$"
)

#: 任何形式的 `名字 = Character(...)` —— 认出来就说明这个名字能说话。
_CHARACTER_CTOR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*Character[ \t]*\(")

#: 看起来就是 `%s` / `%(名字)s` 形态的替换。`%%` 是它的转义，先去掉再找。
#: 只报 info：`%` 那套由 `config.old_substitutions` 控制，包里读不到那个开关的真实值，
#: 所以不敢断言"一定会出错"，只提示作者确认（见 `renpy._escape_renpy_string` 的说明）。
_PERCENT_SUB_RE = re.compile(r"%\([^)]*\)[A-Za-z]|%[sdif]")

#: 不需要 define 就能说话的引擎内置名（`narrator` 是引擎自带的旁白）。
_BUILTIN_SPEAKERS = {
    "narrator", "extend", "centered", "vcentered", "nvl", "name_only", "dynamic",
}

SEVERITY_ERROR = "error"
SEVERITY_WARN = "warn"
SEVERITY_INFO = "info"


@dataclass(frozen=True)
class RpyFinding:
    """一条体检结论。``line`` 是 1 起的行号；0 表示"整份文件"级别。"""

    code: str
    severity: str
    message: str
    line: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def has_errors(findings: Sequence[RpyFinding]) -> bool:
    """有没有"必须处理"的结论（error 级）。warn/info 只提示，不当失败。"""
    return any(f.severity == SEVERITY_ERROR for f in findings)


def _stress_first(findings: List[RpyFinding]) -> List[RpyFinding]:
    """按"先严重、后行号"排序：作者先看到会崩的那几条。"""
    rank = {SEVERITY_ERROR: 0, SEVERITY_WARN: 1, SEVERITY_INFO: 2}
    return sorted(findings, key=lambda f: (rank.get(f.severity, 9), f.line))


def label_names(text: str) -> List[str]:
    """文本里定义过的 label 名（保序、含重复）。"""
    out: List[str] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        m = _LABEL_RE.match(raw)
        if m:
            out.append(m.group("name"))
    return out


def validate_script_rpy(text: str) -> List[RpyFinding]:
    """体检一份 .rpy 文本，返回结论（不改动入参）。

    检查项与"为什么是它"：

    - ``dangling_target``（error）：`jump`/`call` 指向的 label 全文都没有 → 玩家卡死。
    - ``duplicate_label``（error）：同名 label 定义两次 → Ren'Py 拒绝加载。
    - ``unescaped_bracket``（error）：台词里有没转义的 `[` → 被当成变量替换。
    - ``sanitized_name``（warn）：label/目标名落成了安全化兜底名 `unnamed`
      → 原名（中文/符号）被改写，跳转网已经不是作者写的那张了。
    - ``start_label_missing``（warn）：全文没有 `label start:` → Ren'Py 找不到入口。
    - ``unknown_speaker``（warn）：说话人既没有 `= Character(...)` 也不是引擎内置名。
    - ``percent_substitution``（info）：台词里有 `%s`/`%(名字)s` 形态（见上）。
    - ``skipped_by_exporter``（warn）：导出器留下了 `# [VNSS] …` 标记
      （跳过了变量赋值 / 特效 / 条件，或把未知角色按旁白输出了）。
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")

    labels: List[Tuple[str, int]] = []
    targets: List[Tuple[str, int]] = []
    says: List[Tuple[str, str, int]] = []
    markers: List[int] = []

    for lineno, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#"):
            if MARKER_PREFIX in s:
                markers.append(lineno)
            continue
        m = _LABEL_RE.match(raw)
        if m:
            labels.append((m.group("name"), lineno))
            continue
        m = _TARGET_RE.match(raw)
        if m:
            target = m.group("target")
            if target not in _NON_LABEL_TARGETS:
                targets.append((target, lineno))
            continue
        if s.split()[0] in _NON_SAY_KEYWORDS:
            continue
        m = _SAY_RE.match(raw)
        if m:
            says.append((m.group("who") or "", m.group("text"), lineno))

    defined_speakers = {m.group(1) for m in _CHARACTER_CTOR_RE.finditer("\n".join(lines))}
    known_labels = {name for name, _ in labels}

    findings: List[RpyFinding] = []

    # ---- 重名 label
    first_seen: Dict[str, int] = {}
    for name, lineno in labels:
        if name in first_seen:
            findings.append(
                RpyFinding(
                    "duplicate_label",
                    SEVERITY_ERROR,
                    f"label「{name}」定义了多次（第 {first_seen[name]} 行和第 {lineno} 行）："
                    "Ren'Py 会拒绝加载这份脚本。",
                    lineno,
                )
            )
        else:
            first_seen[name] = lineno

    # ---- label 名被安全化改写（原名含中文/符号）
    for name, lineno in labels:
        if name == IDENT_FALLBACK:
            findings.append(
                RpyFinding(
                    "sanitized_name",
                    SEVERITY_WARN,
                    f"第 {lineno} 行的 label 名被安全化成了「{IDENT_FALLBACK}」："
                    "原名含中文或符号，Ren'Py 的 label 只认 ASCII 标识符。"
                    "多个这样的 label 会互相覆盖，建议改成英文名。",
                    lineno,
                )
            )

    # ---- 悬空跳转（判定复用块级体检的 `missing_targets`）
    for target in missing_targets(known_labels, [t for t, _ in targets]):
        lineno = next(ln for t, ln in targets if t == target)
        findings.append(
            RpyFinding(
                "dangling_target",
                SEVERITY_ERROR,
                f"第 {lineno} 行跳转到「{target}」，但整份脚本里没有这个 label："
                "玩家会卡在这里（Ren'Py 报 could not find label）。",
                lineno,
            )
        )
    for target, lineno in targets:
        if target == IDENT_FALLBACK:
            findings.append(
                RpyFinding(
                    "sanitized_name",
                    SEVERITY_WARN,
                    f"第 {lineno} 行的跳转目标被安全化成了「{IDENT_FALLBACK}」："
                    "原名含中文或符号，导出后跳转的是另一个名字。",
                    lineno,
                )
            )

    # ---- 入口点
    if "start" not in known_labels:
        findings.append(
            RpyFinding(
                "start_label_missing",
                SEVERITY_WARN,
                "整份脚本里没有 `label start:`：Ren'Py 启动时找不到入口。"
                "整包导出（zip）会自动补一条 start 桥，单文件下载走的是同一条路径。",
            )
        )

    # ---- 台词文本
    for who, say_text, lineno in says:
        if "[" in say_text.replace("[[", ""):
            findings.append(
                RpyFinding(
                    "unescaped_bracket",
                    SEVERITY_ERROR,
                    f"第 {lineno} 行的台词里有没转义的 `[`：Ren'Py 会把它当成变量替换"
                    "（`[名字]` 取变量的值），文本会被吞掉或直接报错。"
                    "字面方括号要写成 `[[`。",
                    lineno,
                )
            )
        if _PERCENT_SUB_RE.search(say_text.replace("%%", "")):
            findings.append(
                RpyFinding(
                    "percent_substitution",
                    SEVERITY_INFO,
                    f"第 {lineno} 行的台词里有 `%s` / `%(名字)s` 形态的文本："
                    "在打开了 config.old_substitutions 的 Ren'Py 里它也是变量替换。"
                    "如果那是要显示的字面文本，写成 `%%`。",
                    lineno,
                )
            )
        if who and who not in defined_speakers and who not in _BUILTIN_SPEAKERS:
            findings.append(
                RpyFinding(
                    "unknown_speaker",
                    SEVERITY_WARN,
                    f"第 {lineno} 行的说话人「{who}」在这份脚本里没有 "
                    "`= Character(...)` 定义：如果角色卡定义在别的文件里可以忽略，"
                    "否则 Ren'Py 运行到这里会 NameError。",
                    lineno,
                )
            )

    # ---- 导出器自己的标记（跳过了什么、降级了什么）
    if markers:
        preview = "、".join(f"第 {n} 行" for n in markers[:5])
        more = f" 等 {len(markers)} 处" if len(markers) > 5 else ""
        findings.append(
            RpyFinding(
                "skipped_by_exporter",
                SEVERITY_WARN,
                f"导出时留下了 {len(markers)} 处标记（{preview}{more}）："
                "其中有的是**跳过了内容**（变量赋值 / 特效 / 条件 / 找不到的角色），"
                "有的是**名字被安全化改写**。"
                f"搜索 `{MARKER_PREFIX}` 可以看到每一处的原文与原因。",
                markers[0],
            )
        )

    return _stress_first(findings)


def validate_project_rpy(project: Any, *, adaptive_reader: bool = False) -> List[RpyFinding]:
    """工程 → 下载产物（`export_script_rpy`）→ 体检结论。

    单独包一层是为了让"体检的文本"和"下载的文本"在代码上**同源**：
    两边都调 `export_script_rpy(project, adaptive_reader=...)`，
    任何一个参数（尤其是 adaptive_reader）变了两边一起变。
    """
    from app.core.renpy import export_script_rpy

    return validate_script_rpy(
        export_script_rpy(project, adaptive_reader=adaptive_reader)
    )


def summarize(findings: Sequence[RpyFinding]) -> Dict[str, Any]:
    """给接口用的紧凑摘要：数量 + 是否可下载。"""
    counts = {SEVERITY_ERROR: 0, SEVERITY_WARN: 0, SEVERITY_INFO: 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return {
        "ok": not has_errors(findings),
        "counts": counts,
        "findings": [f.to_dict() for f in findings],
    }


def first_error(findings: Sequence[RpyFinding]) -> Optional[RpyFinding]:
    """第一条 error 级结论（LLM 那条路用它决定要不要回退成确定性解析）。"""
    return next((f for f in findings if f.severity == SEVERITY_ERROR), None)
