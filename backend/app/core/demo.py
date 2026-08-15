"""Ported from packages/core/src/demo.ts"""
from __future__ import annotations

import time

from app.domain.types import VnProject

from .project import normalize_project


def create_demo_project() -> VnProject:
    return normalize_project(
        {
            "id": "demo-rainy-station",
            "title": "雨夜车站",
            "logline": "末班车延误的夜里，两个陌生人分享一把伞，却发现彼此寻找的是同一个人。",
            "genre": "悬疑 / 情感",
            "bible": {
                "world": "现代都市。雨季漫长。部分车站的广播与电子屏会在特定夜晚「失灵」，仿佛被另一套时刻表覆盖。",
                "background": "林夏的姐姐失踪三周，最后出现记录停在这座换乘站。周屿自称过路人，却对站内动线过分熟悉。",
                "outline": "1. 雨夜月台相遇\n2. 伞下试探：天桥与便利店视线\n3. 进入停用站厅\n4. 维修通道发现换乘记号\n5. 抉择：相信周屿或独自追查",
                "themes": "信任与隐瞒；城市空间中的迷失；「寻找」本身改变寻找者",
            },
            "characters": [
                {
                    "id": "linxia",
                    "defineName": "linxia",
                    "displayName": "林夏",
                    "color": "#7eb8da",
                    "voice": "克制、短句、观察力强，不轻易示弱",
                    "bio": "24 岁，图书管理员。姐姐失踪三周。",
                    "imageTag": "linxia",
                    "relationships": "姐姐（失踪）；对周屿保持戒备",
                },
                {
                    "id": "zhouyu",
                    "defineName": "zhouyu",
                    "displayName": "周屿",
                    "color": "#c4a574",
                    "voice": "温和但回避关键问题，习惯用笑带过",
                    "bio": "身份不明。对车站布局异常熟悉。",
                    "imageTag": "zhouyu",
                    "relationships": "与林夏姐姐可能有旧识（未证实）",
                },
            ],
            "mapStyle": "default",
            "locations": [
                {
                    "id": "loc-platform",
                    "name": "雨夜月台",
                    "imageTag": "bg station_night_rain",
                    "description": "末班车电子屏常跳「延误」。雨把站台洗得很亮。",
                    "tags": ["户外", "开场"],
                    "mapX": 1580,
                    "mapY": 1280,
                    "elementKind": "station",
                    "icon": "🚉",
                    "color": "#5b8def",
                },
                {
                    "id": "loc-hall",
                    "name": "停用站厅",
                    "imageTag": "bg station_hall_closed",
                    "description": "卷帘半落，灯光昏黄，墙面有旧换乘贴纸。",
                    "tags": ["室内", "关键"],
                    "mapX": 1980,
                    "mapY": 1480,
                    "elementKind": "landmark",
                    "icon": "📍",
                    "color": "#b85c38",
                },
                {
                    "id": "loc-tunnel",
                    "name": "维修通道",
                    "imageTag": "bg maintenance_tunnel",
                    "description": "仅员工可入。回声很重。",
                    "tags": ["室内", "隐藏"],
                    "mapX": 2360,
                    "mapY": 1260,
                    "elementKind": "bridge",
                    "icon": "🌉",
                    "color": "#7a8b99",
                },
            ],
            "locationLinks": [
                {
                    "id": "link-1",
                    "fromId": "loc-platform",
                    "toId": "loc-hall",
                    "relation": "leads_to",
                    "note": "下楼梯进入",
                },
                {
                    "id": "link-2",
                    "fromId": "loc-hall",
                    "toId": "loc-tunnel",
                    "relation": "contains",
                    "note": "员工门后",
                },
                {
                    "id": "link-3",
                    "fromId": "loc-platform",
                    "toId": "loc-hall",
                    "relation": "visible_from",
                    "note": "隔着玻璃可见部分站厅",
                },
            ],
            "characterLinks": [
                {
                    "id": "clink-1",
                    "fromId": "linxia",
                    "toId": "zhouyu",
                    "label": "戒备的陌生人",
                    "evidence": [
                        {
                            "source": "card",
                            "field": "relationships",
                            "quote": "对周屿保持戒备",
                        }
                    ],
                    "acceptedAt": "2024-01-01T00:00:00+00:00",
                },
            ],
            "timeline": [
                {
                    "id": "tl-1",
                    "title": "雨夜相遇",
                    "when": "第一晚 · 末班延误",
                    "summary": "林夏与周屿在月台相遇，伞下试探开始。",
                    "order": 1,
                    "chapterRef": "ch1",
                    "evidence": [
                        {
                            "source": "script",
                            "chapterId": "ch1",
                            "quote": "雨夜月台，林夏等到延误通知，遇见周屿。",
                        }
                    ],
                    "acceptedAt": "2024-01-01T00:00:00+00:00",
                },
                {
                    "id": "tl-2",
                    "title": "天桥与便利店",
                    "when": "第一晚 · 延误延长",
                    "summary": "伞下试探；周屿对站外动线过分清楚。",
                    "order": 2,
                    "chapterRef": "ch2",
                    "evidence": [
                        {"source": "bible", "field": "outline", "quote": "伞下试探"}
                    ],
                    "acceptedAt": "2024-01-01T00:00:00+00:00",
                },
                {
                    "id": "tl-3",
                    "title": "进入停用站厅",
                    "when": "第一晚 · 稍后",
                    "summary": "跟随可疑线索进入站厅。",
                    "order": 3,
                    "chapterRef": "ch3",
                    "evidence": [
                        {
                            "source": "script",
                            "chapterId": "ch3",
                            "quote": "进入停用站厅",
                        }
                    ],
                    "acceptedAt": "2024-01-01T00:00:00+00:00",
                },
                {
                    "id": "tl-4",
                    "title": "换乘记号",
                    "when": "第一晚 · 更深",
                    "summary": "维修通道里发现姐姐留下的记号。",
                    "order": 4,
                    "chapterRef": "ch4",
                    "evidence": [
                        {
                            "source": "script",
                            "chapterId": "ch4",
                            "quote": "维修通道里发现姐姐留下的记号",
                        }
                    ],
                    "acceptedAt": "2024-01-01T00:00:00+00:00",
                },
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "末班广播",
                    "synopsis": "雨夜月台，林夏等到延误通知，遇见周屿。",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {
                            "type": "scene",
                            "image": "bg station_night_rain",
                            "transition": "fade",
                        },
                        {"type": "show", "image": "linxia neutral", "at": "left"},
                        {
                            "type": "narration",
                            "text": "雨把站台洗成一条发亮的河。末班车的电子屏跳了两下，变成刺眼的「延误」。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "……又是这样。",
                        },
                        {"type": "show", "image": "zhouyu smile", "at": "right"},
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "这把伞还能再挤一个人。如果你不介意潮湿的礼貌的话。",
                        },
                        {
                            "type": "menu",
                            "id": "umbrella",
                            "prompt": "你要怎么做？",
                            "choices": [
                                {"text": "接过伞沿", "jump": "accept_umbrella"},
                                {"text": "婉拒，继续等", "jump": "refuse_umbrella"},
                            ],
                        },
                        {
                            "type": "label",
                            "id": "accept_umbrella",
                            "name": "accept_umbrella",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "谢谢。我在等一个人……也许她不会来了。",
                        },
                        {"type": "jump", "target": "talk_rain"},
                        {
                            "type": "label",
                            "id": "refuse_umbrella",
                            "name": "refuse_umbrella",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "不用。雨停之前我还站得住。",
                        },
                        {"type": "label", "id": "talk_rain", "name": "talk_rain"},
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "那个人……也喜欢在这种天气失踪吗？",
                        },
                        {"type": "jump", "target": "ch2_bridge"},
                    ],
                },
                {
                    "id": "ch2",
                    "title": "伞下的地图",
                    "synopsis": "延误继续。两人谈到站外天桥与便利店；周屿的路线知识让林夏起疑。",
                    "blocks": [
                        {"type": "label", "id": "ch2_bridge", "name": "ch2_bridge"},
                        {
                            "type": "scene",
                            "image": "bg overpass_rain",
                            "transition": "dissolve",
                        },
                        {
                            "type": "narration",
                            "text": "延误再次延长。伞沿外，人行天桥的灯一盏一盏灭了半边，像被谁掐灭。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "从月台往东，过天桥就能看见那家二十四小时便利店。你姐姐……以前常在那儿买热饮。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "你怎么知道？",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "路过几次。雨天热罐头汤卖得特别快——随便聊聊。",
                        },
                        {
                            "type": "narration",
                            "text": "便利店的玻璃门反着霓虹。林夏没有走过去，只把伞柄握紧了一点。",
                        },
                        {
                            "type": "menu",
                            "id": "ch2_choice",
                            "prompt": "你要怎么试探？",
                            "choices": [
                                {"text": "追问他为何熟悉动线", "jump": "ch2_ask"},
                                {"text": "提议去便利店避雨", "jump": "ch2_store"},
                            ],
                        },
                        {"type": "label", "id": "ch2_ask", "name": "ch2_ask"},
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "过路人不会把换乘口背得这么熟。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "也许我只是……比你更怕错过末班车。",
                        },
                        {"type": "jump", "target": "ch2_end"},
                        {"type": "label", "id": "ch2_store", "name": "ch2_store"},
                        {
                            "type": "scene",
                            "image": "bg convenience_store",
                            "transition": "fade",
                        },
                        {
                            "type": "narration",
                            "text": "便利店里暖气发闷。冷柜嗡嗡响，像另一套时刻表在低声倒数。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "她喜欢姜茶。货架第三排——以前是。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "「以前」两个字，你用得太顺口了。",
                        },
                        {"type": "label", "id": "ch2_end", "name": "ch2_end"},
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "站厅那边卷帘没落死。你要是敢下去，我可以带路。",
                        },
                        {"type": "jump", "target": "ch3_hall"},
                    ],
                },
                {
                    "id": "ch3",
                    "title": "半落的卷帘",
                    "synopsis": "两人潜入停用站厅；墙面旧贴纸与失灵广播指向更深的通道。",
                    "blocks": [
                        {"type": "label", "id": "ch3_hall", "name": "ch3_hall"},
                        {
                            "type": "scene",
                            "image": "bg station_hall_closed",
                            "transition": "fade",
                        },
                        {"type": "show", "image": "linxia wary", "at": "left"},
                        {"type": "show", "image": "zhouyu neutral", "at": "right"},
                        {
                            "type": "narration",
                            "text": "停用站厅的灯只亮三分之一。卷帘半落，风从缝里灌进来，带着铁锈味。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "广播还在响……可外面电子屏明明写着延误。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "这里听的是旧时刻表。跟上面那套不是同一回事。",
                        },
                        {
                            "type": "narration",
                            "text": "墙上一排褪色的换乘贴纸。其中一张被指甲抠过，露出下面更旧的记号——像医院箭头被改成车站符号。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "她最后一条定位……在附近医院晃过。可监控说她从没进去。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "有人会用医院当幌子。真正的路，在员工门后。",
                        },
                        {
                            "type": "menu",
                            "id": "ch3_door",
                            "prompt": "员工门虚掩着。",
                            "choices": [
                                {"text": "跟他进去", "jump": "ch3_follow"},
                                {"text": "先拍照留证再进", "jump": "ch3_photo"},
                            ],
                        },
                        {"type": "label", "id": "ch3_follow", "name": "ch3_follow"},
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "走。但你走在我前面。",
                        },
                        {"type": "jump", "target": "ch4_tunnel"},
                        {"type": "label", "id": "ch3_photo", "name": "ch3_photo"},
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "等一下。我要把贴纸和门牌拍下来。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "好。闪光灯别开太久——这里不喜欢被记住。",
                        },
                        {"type": "jump", "target": "ch4_tunnel"},
                    ],
                },
                {
                    "id": "ch4",
                    "title": "维修通道",
                    "synopsis": "维修通道尽头出现姐姐的换乘记号；周屿的隐瞒被逼到边缘。",
                    "blocks": [
                        {"type": "label", "id": "ch4_tunnel", "name": "ch4_tunnel"},
                        {
                            "type": "scene",
                            "image": "bg maintenance_tunnel",
                            "transition": "dissolve",
                        },
                        {
                            "type": "narration",
                            "text": "维修通道又窄又长。脚步声叠成回音，像有第三个人在同一节拍里走路。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "到头了。看左手边——她喜欢在墙根留「换乘」两字的缩写。",
                        },
                        {
                            "type": "narration",
                            "text": "石灰墙上果然有粉笔痕：两道斜线，中间一个小圆。旁边还歪歪扭扭写着「公园东门见」。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "公园东门……她失踪前跟我说要去那里喂流浪猫。你为什么先看见？",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "因为我也在找她。只是我没资格先开口。",
                        },
                        {
                            "type": "menu",
                            "id": "ch4_trust",
                            "prompt": "粉笔还没干透。",
                            "choices": [
                                {"text": "暂时信他，一起去公园", "jump": "ch4_park"},
                                {"text": "独自留下，核对记号", "jump": "ch4_alone"},
                            ],
                        },
                        {"type": "label", "id": "ch4_park", "name": "ch4_park"},
                        {
                            "type": "scene",
                            "image": "bg park_east_gate_rain",
                            "transition": "fade",
                        },
                        {
                            "type": "narration",
                            "text": "公园东门的灯坏了一半。雨打在铁栅栏上，像有人在远处轻轻敲门。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "如果记号是诱饵，我们也算踩中了。你还要继续吗？",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "继续。我要听完整的那套旧时刻表。",
                        },
                        {"type": "jump", "target": "ch4_end"},
                        {"type": "label", "id": "ch4_alone", "name": "ch4_alone"},
                        {
                            "type": "dialogue",
                            "characterId": "linxia",
                            "text": "你先出去。记号我自己核。",
                        },
                        {
                            "type": "dialogue",
                            "characterId": "zhouyu",
                            "text": "……好。通道尽头右转能回月台。别在这里待过久。",
                        },
                        {"type": "label", "id": "ch4_end", "name": "ch4_end"},
                        {
                            "type": "narration",
                            "text": "雨还没停。城市像一张被水泡皱的地图，有些路只在延误的夜里才接通。",
                        },
                    ],
                },
            ],
        }
    )


def empty_project(title: str = "未命名剧本") -> VnProject:
    return normalize_project(
        {
            "id": f"proj-{int(time.time() * 1000)}",
            "title": title,
            "characters": [],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "blocks": [{"type": "label", "id": "start", "name": "start"}],
                }
            ],
            "bible": {},
            "locations": [],
            "locationLinks": [],
        }
    )
