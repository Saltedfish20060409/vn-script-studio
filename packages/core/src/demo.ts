import type { ScriptBlock, VnProject } from "./types.js";
import { normalizeProject } from "./project.js";

export function createDemoProject(): VnProject {
  return normalizeProject({
    id: "demo-rainy-station",
    title: "雨夜车站",
    logline:
      "末班车延误的夜里，两个陌生人分享一把伞，却发现彼此寻找的是同一个人。",
    genre: "悬疑 / 情感",
    bible: {
      world:
        "现代都市。雨季漫长。部分车站的广播与电子屏会在特定夜晚「失灵」，仿佛被另一套时刻表覆盖。",
      background:
        "林夏的姐姐失踪三周，最后出现记录停在这座换乘站。周屿自称过路人，却对站内动线过分熟悉。",
      outline:
        "1. 雨夜月台相遇\n2. 伞下试探与谎言\n3. 进入停用站厅\n4. 发现姐姐留下的换乘记号\n5. 抉择：相信周屿或独自追查",
      themes: "信任与隐瞒；城市空间中的迷失；「寻找」本身改变寻找者",
    },
    characters: [
      {
        id: "linxia",
        defineName: "linxia",
        displayName: "林夏",
        color: "#7eb8da",
        voice: "克制、短句、观察力强，不轻易示弱",
        bio: "24 岁，图书管理员。姐姐失踪三周。",
        imageTag: "linxia",
        relationships: "姐姐（失踪）；对周屿保持戒备",
      },
      {
        id: "zhouyu",
        defineName: "zhouyu",
        displayName: "周屿",
        color: "#c4a574",
        voice: "温和但回避关键问题，习惯用笑带过",
        bio: "身份不明。对车站布局异常熟悉。",
        imageTag: "zhouyu",
        relationships: "与林夏姐姐可能有旧识（未证实）",
      },
    ],
    mapStyle: "mystery",
    locations: [
      {
        id: "loc-platform",
        name: "雨夜月台",
        imageTag: "bg station_night_rain",
        description: "末班车电子屏常跳「延误」。雨把站台洗得很亮。",
        tags: ["户外", "开场"],
        mapX: 1580,
        mapY: 1280,
        elementKind: "station",
        icon: "🚉",
        color: "#5b8def",
      },
      {
        id: "loc-hall",
        name: "停用站厅",
        imageTag: "bg station_hall_closed",
        description: "卷帘半落，灯光昏黄，墙面有旧换乘贴纸。",
        tags: ["室内", "关键"],
        mapX: 1980,
        mapY: 1480,
        elementKind: "landmark",
        icon: "📍",
        color: "#b85c38",
      },
      {
        id: "loc-tunnel",
        name: "维修通道",
        imageTag: "bg maintenance_tunnel",
        description: "仅员工可入。回声很重。",
        tags: ["室内", "隐藏"],
        mapX: 2360,
        mapY: 1260,
        elementKind: "bridge",
        icon: "🌉",
        color: "#7a8b99",
      },
    ],
    locationLinks: [
      {
        id: "link-1",
        fromId: "loc-platform",
        toId: "loc-hall",
        relation: "leads_to",
        note: "下楼梯进入",
      },
      {
        id: "link-2",
        fromId: "loc-hall",
        toId: "loc-tunnel",
        relation: "contains",
        note: "员工门后",
      },
      {
        id: "link-3",
        fromId: "loc-platform",
        toId: "loc-hall",
        relation: "visible_from",
        note: "隔着玻璃可见部分站厅",
      },
    ],
    characterLinks: [
      {
        id: "clink-1",
        fromId: "linxia",
        toId: "zhouyu",
        label: "戒备的陌生人",
      },
    ],
    timeline: [
      {
        id: "tl-1",
        title: "雨夜相遇",
        when: "第一晚 · 末班延误",
        summary: "林夏与周屿在月台相遇，伞下试探开始。",
        order: 1,
        chapterRef: "ch1",
      },
      {
        id: "tl-2",
        title: "进入停用站厅",
        when: "第一晚 · 稍后",
        summary: "跟随可疑线索进入站厅。",
        order: 2,
      },
    ],
    chapters: [
      {
        id: "ch1",
        title: "末班广播",
        synopsis: "雨夜月台，林夏等到延误通知，遇见周屿。",
        blocks: [
          { type: "label", id: "start", name: "start" },
          { type: "scene", image: "bg station_night_rain", transition: "fade" },
          { type: "show", image: "linxia neutral", at: "left" },
          {
            type: "narration",
            text: "雨把站台洗成一条发亮的河。末班车的电子屏跳了两下，变成刺眼的「延误」。",
          },
          {
            type: "dialogue",
            characterId: "linxia",
            text: "……又是这样。",
          },
          { type: "show", image: "zhouyu smile", at: "right" },
          {
            type: "dialogue",
            characterId: "zhouyu",
            text: "这把伞还能再挤一个人。如果你不介意潮湿的礼貌的话。",
          },
          {
            type: "menu",
            id: "umbrella",
            prompt: "你要怎么做？",
            choices: [
              { text: "接过伞沿", jump: "accept_umbrella" },
              { text: "婉拒，继续等", jump: "refuse_umbrella" },
            ],
          },
          { type: "label", id: "accept_umbrella", name: "accept_umbrella" },
          {
            type: "dialogue",
            characterId: "linxia",
            text: "谢谢。我在等一个人……也许她不会来了。",
          },
          { type: "jump", target: "talk_rain" },
          { type: "label", id: "refuse_umbrella", name: "refuse_umbrella" },
          {
            type: "dialogue",
            characterId: "linxia",
            text: "不用。雨停之前我还站得住。",
          },
          { type: "label", id: "talk_rain", name: "talk_rain" },
          {
            type: "dialogue",
            characterId: "zhouyu",
            text: "那个人……也喜欢在这种天气失踪吗？",
          },
        ],
      },
    ],
  });
}

export function emptyProject(title = "未命名剧本"): VnProject {
  return normalizeProject({
    id: `proj-${Date.now()}`,
    title,
    characters: [],
    chapters: [
      {
        id: "ch1",
        title: "第一章",
        blocks: [{ type: "label", id: "start", name: "start" }] as ScriptBlock[],
      },
    ],
    bible: {},
    locations: [],
    locationLinks: [],
  });
}
