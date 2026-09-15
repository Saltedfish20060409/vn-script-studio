"""素材引用审计：剧本里引用了哪些图/音、有没有明显写错的。

现状说明（要诚实）：项目里没有素材上传与存储，剧本用**名字/路径**引用素材
（`scene bg room`、`play music bgm/rain.ogg`）。所以这里做的是引用侧审计：

- **清单**：按类别列出所有被引用的素材及出现章节 —— 这就是作者要去准备的文件清单，
  导出成 Ren'Py 工程后必须放在 game/images、game/audio 下；
- **疑似写错**：`scene/show/hide` 里的 image 名如果既不是立绘 imageTag、也不是角色 imageTag，
  也没有在别处被重复使用，很可能是拼错了（这类错误在 Ren'Py 里表现为运行时缺图）；
- **音频**：逐条列出（bgm/sound/voice），数量与分布一目了然。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List

from app.domain.types import VnProject


def _walk(blocks: List[Any]) -> Iterable[Dict[str, Any]]:
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        yield b
        for choice in b.get("choices") or []:
            if isinstance(choice, dict):
                yield from _walk(choice.get("blocks") or [])
        for branch in b.get("branches") or []:
            if isinstance(branch, dict):
                yield from _walk(branch.get("blocks") or [])


def _image_first_token(image: str) -> str:
    """`linxia sad` → `linxia`（Ren'Py 的 image tag 是第一个词）。"""
    return (image or "").strip().split(" ")[0]


def audit_assets(project: VnProject) -> Dict[str, Any]:
    images: Counter = Counter()
    image_where: Dict[str, List[str]] = {}
    audio: Dict[str, Counter] = {"music": Counter(), "sound": Counter(), "voice": Counter()}

    for ch in project.chapters or []:
        for b in _walk(ch.blocks or []):
            btype = b.get("type")
            if btype in ("scene", "show", "hide"):
                img = str(b.get("image") or "").strip()
                if img:
                    images[img] += 1
                    image_where.setdefault(img, [])
                    if ch.id not in image_where[img]:
                        image_where[img].append(ch.id)
            elif btype in ("music", "sound", "voice"):
                if (b.get("action") or "play") == "stop":
                    continue
                f = str(b.get("file") or "").strip()
                if f:
                    audio[btype][f] += 1

    # 已声明的图像 tag：立绘 imageTag + 角色 imageTag
    declared_tags = set()
    for s in project.sprites or []:
        tag = getattr(s, "imageTag", None)
        if tag:
            declared_tags.add(str(tag))
    for c in project.characters or []:
        tag = getattr(c, "imageTag", None)
        if tag:
            declared_tags.add(str(tag))

    suspicious = [
        {"image": img, "uses": n, "chapters": image_where.get(img, [])}
        for img, n in images.items()
        # `bg ...` / `cg ...` 是背景与 CG 的通用命名约定，没有"声明"可言，不判可疑；
        # 其余首词（通常是角色立绘 tag）对不上任何立绘/角色 imageTag 时才提醒——
        # 这类错误在 Ren'Py 里表现为运行时缺图，是真正值得报的。
        if _image_first_token(img) not in declared_tags
        and _image_first_token(img).lower() not in ("bg", "cg", "black", "white")
    ]
    suspicious.sort(key=lambda x: (-x["uses"], x["image"]))

    unused_tags = sorted(
        t for t in declared_tags if not any(_image_first_token(i) == t for i in images)
    )

    return {
        "images": {
            "total": len(images),
            "items": [{"image": i, "uses": n, "chapters": image_where.get(i, [])} for i, n in images.most_common()],
            "suspicious": suspicious,
        },
        "audio": {
            kind: {
                "total": len(counter),
                "items": [{"file": f, "uses": n} for f, n in counter.most_common()],
            }
            for kind, counter in audio.items()
        },
        "declaredTags": sorted(declared_tags),
        "unusedTags": unused_tags,
        "notes": [
            "项目不含素材上传/存储：这里审计的是**引用**。导出 Ren'Py 工程后，"
            "图片放 game/images、音频放 game/audio，路径要与这里一致。",
            "「疑似写错」列表只对图像做判断（用立绘/角色的 imageTag 比对）；"
            "音频无法校验文件是否存在，所以只列清单。",
        ],
    }
