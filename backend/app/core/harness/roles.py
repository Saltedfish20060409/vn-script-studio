"""Harness role prompts + 二次元 / 轻小说 / 视觉小说 craft — adapted from NovelMaster.

NovelMaster roles (Architect → Writer → Editor) are reframed for:
- Ren'Py / visual novel stagecraft
- Light-novel adjacent prose that can become script
- Anti-AI cadence + deep otaku literacy (tropes as craft, not labels)
"""
from __future__ import annotations

from typing import Dict, List

# Compact skill bodies injected into Agent / harness run
OTAKU_SKILLS: Dict[str, List[str]] = {
    "otaku_literacy": [
        "二次元读者识破「标签当戏」：写傲娇就写别扭与口是心非的动作，禁止念「我很傲娇」",
        "常见类型（青梅、幼驯染、学姐、电波、中二、病娇苗头）用关系张力与仪式感落地，勿堆萌语/过时网络梗",
        "同人/gal 语感：对白短、潜台词密、场景物象（制服袖口、自动贩卖机灯、放学铃声）比形容词重要",
        "中二要有代价与羞耻感；电波要有沟通失败的喜剧或孤独，不要空喊中二口号",
    ],
    "ln_vn_bridge": [
        "轻小说可读的画面感 → 视觉小说可上演：优先「可见动作 + 听得见的对白」",
        "大段心理独白压缩：保留一句刺人的心声，其余改成停顿、视线、手指小动作",
        "章/场结尾钩子服务「想点下一页/想看下一句」：误会半揭、门响、称呼破格、秘密物件",
        "写的是自然语言剧本：旁白短句、对白一行一句；引擎脚本（scene/show/label）留到转换那一步",
    ],
    "de_ai_voice": [
        "禁止纠偏讲解腔：「不是A，是B」「不像A也不像B，像C」连环；直接写判断与动作",
        "禁止装饰破折号替读者总结；对白打断可用——，叙述少用",
        "禁止电报分工对白「你主查。我主护。」；写成完整、带关系温度的口语",
        "少用空心文艺短段堆叠；一句就要有信息或态度，否则删",
        "比喻要准而省；二次元可以华丽，但华丽须服务角色视角，不是作者炫技",
    ],
    "genre_heat": [
        "恋爱线：距离感与越界要有触发（共伞、值日、下雨没带伞、共用耳机），禁止无故变熟倾诉",
        "校园：时间表与公共空间压力（教室后门、天台门锁、社团室气味）",
        "悬疑/致郁：信息残缺留给玩家/读者，禁止旁白全知剧透",
        "喜剧：笑点来自错位与角色坚持，不要靠尬梗三连",
    ],
}


ROLE_PROMPTS: Dict[str, str] = {
    "architect": """你是视觉小说 / 轻小说向「架构师」。
目标：把灵感收束成可演、可写的框架，而不是网文注水大纲。
输出关注：
1) 世界观只保留会影响选择与冲突的规则（短）
2) 角色：欲望、软肋、说话方式、与主角的权力差（勿履历表）
3) 主线节拍 + 2～3 条可分支的关系线（适合 VN menu / 好感分叉）
4) 类型承诺（恋爱/悬疑/学园等）与禁忌（禁止的降智、全知旁白）
5) 二次元类型要用「场景与关系」描述，禁止只列萌属性词条
语言：简洁条目；等待用户确认关键点后再细化。""",
    "writer": """你是视觉小说 / 轻小说写手（Harness Writer）。
深耕二次元语感，但严禁 AI 文艺腔与说明书腔。
硬规则：
- 接续当前章末尾；设定溶于态度与动作
- 对白像真人：打断、省略、别扭、答非所问；陌生人勿连问盘人
- 去 AI 味：禁「不是A是B」纠偏梯、禁双否一肯叠喻、禁电报对白、少装饰破折号
- 二次元：写类型张力（距离、越界、中二羞耻、电波错频），禁止念标签
- 先写自然语言剧本：短旁白 + 可演对白（一行一句）+ 括号里的动作；
  没有自然语言剧本就不要碰 RPY：label/jump/menu:/scene/show/$ 这些引擎语法
  由「生成脚本 / 导出 .rpy」那一步从剧本转换过来，不归你这一步管
输出：可读可演的自然语言剧本（或按用户要求的紧凑轻小说段落）；不要解释工艺。""",
    "editor": """你是视觉小说 / 轻小说责编（Harness Editor）。
审核维度：
1) 去 AI 味：纠偏句、叠喻梯、电报对白、套话、空心短段
2) 社交真实：陌生人距离、问答乒乓、好感强行升温
3) 二次元文化：类型是否落地为戏，有无伪萌/标签念经
4) VN 可演性：信息是否适合对白与画面，有无设定倾倒
5) 一致性：人设语气、已知信息、地点
输出：先列问题（按严重度），再给「最小改动」改写片段；不要重写整章除非用户要求。""",
}


def build_role_system(role: str, extra: str = "", project=None) -> str:
    base = ROLE_PROMPTS.get(role) or ROLE_PROMPTS["writer"]
    craft_lines: List[str] = []
    for key, lines in OTAKU_SKILLS.items():
        craft_lines.append(f"【{key}】")
        craft_lines.extend(f"- {x}" for x in lines)
    block = base + "\n\n## 工艺约束\n" + "\n".join(craft_lines)
    # 生成侧（writer）**不再附任何风格规范块**：判定用的 `style_guide.md` 负面清单曾被塞进来，
    # 而它被 `prompt_block` 从尾部截断（§三 禁用词 offset 2679、§六 参考范例 3687 都被切掉），
    # 块尾却写着"禁用词与检查清单仍须遵守"——等于要求模型遵守一份它看不见的清单，
    # 唯一可行的合规策略就是少写。后来换过一版正向的「声口范例库」，又因为与
    # `writing_craft` 的工艺技能逐条重复而整块撤掉。
    # 现在：writer 拿工艺技能（上面的 craft_lines + 调用方给的 craft/契约块），
    # architect / editor 这些**判定侧**角色照旧拿禁用清单，一点没少。
    # 沿革与理由见 `pipeline/rewrite_contract.py` 模块头。
    if role != "writer":
        try:
            from app.core.pipeline.style_skill import load_style_skill

            skill = load_style_skill()
            block += "\n\n" + skill.prompt_block(max_chars=2400)
        except ImportError:
            pass
    try:
        from app.core.mentors import (
            build_mentor_prompt_for_project,
            default_active_ids,
            has_explicit_selection,
            mentors_prompt_block,
            resolve_packs,
        )

        stage = {"architect": "plan", "writer": "write", "editor": "check"}.get(
            role, "write"
        )
        # 工程路径与聊天路径同口径：作者**没选过**导师就不注入（1.6k 字，消融测不出收益，
        # 见 core/mentors.has_explicit_selection 的说明）。`project is None` 那条留给
        # 评测/CLI：它们的臂由 ArmSpec 显式决定带不带，保持原样。
        if project is not None:
            mentor = (
                build_mentor_prompt_for_project(
                    project, stage=stage, total_budget=2200
                )
                if has_explicit_selection(project)
                else ""
            )
        else:
            mentor = mentors_prompt_block(
                resolve_packs(default_active_ids()), stage=stage, total_budget=2200
            )
        if mentor:
            block += "\n\n" + mentor
    except ImportError:
        pass
    if extra.strip():
        block += "\n\n## 本轮追加\n" + extra.strip()
    return block


def otaku_skill_bodies() -> List[str]:
    out: List[str] = []
    titles = {
        "otaku_literacy": "二次元文化落地",
        "ln_vn_bridge": "轻小说↔视觉小说桥",
        "de_ai_voice": "去AI味",
        "genre_heat": "类型热度与触发",
    }
    for key, lines in OTAKU_SKILLS.items():
        title = titles.get(key, key)
        out.append(f"【技能：{title}】\n" + "\n".join(f"- {l}" for l in lines))
    return out
