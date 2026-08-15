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
            parts = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
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
