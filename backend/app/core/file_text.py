"""Extract plain text from user-uploaded reference files for the Agent."""
from __future__ import annotations

import io
import re
from typing import Optional, Tuple

from docx import Document

# Soft caps — keep Agent context budget healthy
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 48_000

_ALLOWED_EXT = (".txt", ".md", ".markdown", ".json", ".csv", ".docx", ".rpy")

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W_RUBY = f"{_W_NS}ruby"
_W_R = f"{_W_NS}r"
_W_T = f"{_W_NS}t"
#: run 的常见容器（超链接、修订、智能标记）：里面的文字同样要取出来
_W_RUN_CONTAINERS = (f"{_W_NS}hyperlink", f"{_W_NS}ins", f"{_W_NS}smartTag")


def _element_text(el) -> str:  # noqa: ANN001
    if el is None:
        return ""
    return "".join(t.text or "" for t in el.iter(_W_T))


def paragraph_text(paragraph) -> str:  # noqa: ANN001
    """段落文本，**认得 Word 的原生注音**（`w:ruby`）。

    为什么不能直接用 `paragraph.text`：它只拼段落下的**直接 run**，而原生注音把
    基准词放在 `<w:ruby><w:rubyBase>` 里、注音放在 `<w:rt>` 里——于是带注音的
    docx（例如本工具导出的投稿稿，或作者从出版社拿回来的返修稿）导进来会**整片丢字**。
    这里按文档顺序走一遍：普通 run 取文本，`w:ruby` 取成 `基准词（注音）`
    （与我们自己的 rp 形态同形，导回工作台后还能被体检认出来）。
    """
    chunks: list[str] = []
    for child in paragraph._p:  # noqa: SLF001 - python-docx 的公开属性就是 _p
        if child.tag == _W_RUBY:
            base = _element_text(child.find(f"{_W_NS}rubyBase"))
            reading = _element_text(child.find(f"{_W_NS}rt"))
            chunks.append(f"{base}（{reading}）" if reading else base)
        elif child.tag == _W_R:
            chunks.append(_element_text(child))
        elif child.tag in _W_RUN_CONTAINERS:
            for run in child.findall(_W_R):
                chunks.append(_element_text(run))
    return "".join(chunks).strip()


def allowed_filename(name: str) -> bool:
    lower = (name or "").lower()
    return any(lower.endswith(ext) for ext in _ALLOWED_EXT)


def extract_text_from_bytes(
    data: bytes, filename: str
) -> Tuple[str, Optional[str]]:
    """Return (text, warning). Raises ValueError on hard failures."""
    if not data:
        raise ValueError("空文件")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"文件过大（上限 {MAX_FILE_BYTES // (1024 * 1024)}MB）")

    name = (filename or "upload.txt").lower()
    if not allowed_filename(name):
        raise ValueError(
            "暂支持 .txt / .md / .json / .csv / .docx / .rpy"
        )

    warning: Optional[str] = None
    if name.endswith(".docx"):
        # Real .docx is a ZIP package; classic .doc / fake rename fails here.
        if not data.startswith(b"PK"):
            raise ValueError(
                "这不是可解析的 .docx（常见原因：仍是旧版 .doc，或只改了后缀）。"
                "请在 Word 里「另存为 → Word 文档 (*.docx)」，或导出/复制为 .txt / .md 再上传。"
                "不需要自行压缩文件。"
            )
        try:
            doc = Document(io.BytesIO(data))
            parts = [
                text
                for text in (paragraph_text(p) for p in doc.paragraphs)
                if text.strip()
            ]
            for table in doc.tables:
                for row in table.rows:
                    cells = [
                        text
                        for text in (
                            paragraph_text(p)
                            for cell in row.cells
                            for p in cell.paragraphs
                        )
                        if text.strip()
                    ]
                    if cells:
                        parts.append(" | ".join(cells))
            text = "\n".join(parts)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "zip" in msg.lower() or "not a zip" in msg.lower():
                raise ValueError(
                    "无法读取该 Word 文件。请另存为 .docx，或改用 .txt / .md。"
                    "不需要自行压缩。"
                ) from exc
            raise ValueError(f"无法解析 Word：{msg}") from exc
    elif name.endswith(".doc"):
        raise ValueError(
            "暂不支持旧版 .doc。请在 Word 中另存为 .docx，或保存为 .txt / .md 后上传。"
        )
    else:
        text = data.decode("utf-8", errors="replace").replace("\x00", "")

    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        raise ValueError("未能提取到可读文本")

    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        warning = f"正文已截断至 {MAX_TEXT_CHARS} 字"

    return text, warning


def format_attachment_block(
    items: list[dict], *, max_total: int = MAX_TEXT_CHARS
) -> str:
    """Build a context section from [{filename, text}, ...]."""
    if not items:
        return ""
    chunks: list[str] = []
    used = 0
    for item in items:
        name = str(item.get("filename") or item.get("name") or "附件")
        body = str(item.get("text") or "").strip()
        if not body:
            continue
        header = f"### 文件：{name}\n"
        room = max_total - used - len(header)
        if room <= 200:
            chunks.append(f"### 文件：{name}\n（篇幅不足，未纳入）")
            break
        if len(body) > room:
            body = body[:room] + "\n…[截断]"
        chunks.append(header + body)
        used += len(header) + len(body)
    if not chunks:
        return ""
    return (
        "## 用户上传参考资料（只作内部参考：可据此提议设定/关系/时间线/大纲，"
        "禁止整段当对白说明书；写入工程须用户明示或 propose_*）\n"
        + "\n\n".join(chunks)
    )
