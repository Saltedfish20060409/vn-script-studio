"""公告接口：欢迎 + 起步指导。内容维护在 NOTICE 常量，改这里即可更新公告。

前端用 version 判断是否已读（localStorage），因此：
- 改文案：直接编辑 NOTICE 文本
- 想让老用户重新看到公告：bump version
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["notice"])

NOTICE = {
    "version": 3,
    "title": "欢迎使用 VN Script Studio 🎬",
    "updatedAt": "2026-08-23",
    "sections": [
        {
            "heading": "欢迎",
            "body": (
                "欢迎来到 VN Script Studio——一个面向视觉小说 / 轻小说创作者的在线写作工作台。"
                "无需安装，打开浏览器就能开始你的第一个剧本。"
            ),
        },
        {
            "heading": "🚀 三步起步",
            "body": (
                "1. 配置 AI：点击右上角「设置」→「模型」页签，填入你的 API Key 与 Base URL"
                "（DeepSeek / OpenAI 兼容均可），保存后即可使用 AI 续写与审稿。\n"
                "2. 调成你喜欢的样子：同页「外观」可改字体大小、日夜主题；"
                "「桌宠」「音乐播放条」「点击特效」都可在设置里开关。\n"
                "3. 开始创作：新建项目，或从示例项目出发——先写角色与大纲，再进章节编辑器写作。"
            ),
        },
        {
            "heading": "📖 界面要点",
            "body": (
                "· 写作页：左侧章节树，中间编辑器（支持 Ren'Py 语法高亮），写完点「AI 审稿」让责编挑毛病。\n"
                "· 角色 / 设定 / 地图：在顶部导航管理，AI 续写时会自动参考这些设定。\n"
                "· 导出：剧本完成后可导出 Word 或 Ren'Py 工程（.rpy），直接开跑。\n"
                "· 听歌：底部播放条支持网易云 / 酷狗 / B站 搜索即播，歌词跟随。"
            ),
        },
        {
            "heading": "💬 一起让它更好",
            "body": (
                "遇到问题、有功能想法，欢迎加作者 QQ：464313944（备注「VNSS 反馈」），"
                "或到 GitHub 仓库提交 Issue / Pull Request。你的每一条建议都在让这个工具变得更好。"
            ),
        },
        {
            "heading": "祝创作顺利",
            "body": "—— VN Script Studio",
        },
    ],
}


@router.get("/notice")
async def get_notice():
    return NOTICE
