import type { LensPackMeta } from "../api/client";

/**
 * 作家卡展示数据与组装——纯展示辅助。
 * state / API 调用 / 选卡逻辑保留在 AgentChat，这里只产出卡片展示元数据。
 */

export const DEFAULT_WRITER = {
  id: null as string | null,
  name: "通用文学编辑",
  role: "默认 · LN/VN 责编",
  blurb:
    "日常对话自动用的编辑底盘：可演对白、信息残缺、场钩子、类型热度。写轻小说/视觉小说时无需切换作家。",
};

const WRITER_CARD_META: Record<
  string,
  { role: string; blurb: string; sort: number }
> = {
  "author-murakami": {
    role: "文学 / 氛围小说",
    blurb: "适合：疏离日常、都市孤独。擅长：留白、重复变奏、克制比喻。",
    sort: 10,
  },
  "author-higashino": {
    role: "悬疑 / 社会派",
    blurb: "适合：本格与社会派谜题。擅长：公平伏笔、误导动机、因果收束。",
    sort: 20,
  },
  "author-watari": {
    role: "轻小说 · 学园恋爱",
    blurb: "适合：别扭青春恋爱。擅长：心理防线、自欺、越界触发与毒舌距离感。",
    sort: 30,
  },
  "author-nishio": {
    role: "轻小说 · 对白密集",
    blurb: "适合：靠嘴推进的故事。擅长：口癖声纹、抬杠逻辑、定义权争夺。",
    sort: 40,
  },
  "author-kamachi": {
    role: "轻小说 · 动作信息战",
    blurb: "适合：异能/战斗快节奏。擅长：信息差、倒计时、短章甩钩。",
    sort: 50,
  },
  "author-nasu": {
    role: "视觉小说 · 规则概念",
    blurb: "适合：异能、神话、规则对决。擅长：设定可演、代价与例外、概念冲突。",
    sort: 60,
  },
  "author-maeda": {
    role: "视觉小说 · 泣きゲー",
    blurb: "适合：催泪向恋爱/亲情。擅长：长蓄力、一句决堤、静场余韵。",
    sort: 70,
  },
  "author-maruto": {
    role: "视觉小说 · 恋爱细腻",
    blurb: "适合：成人向拉扯恋爱。擅长：试探与撤回、对白缝隙、二人私密语法。",
    sort: 80,
  },
  "author-urobuchi": {
    role: "视觉小说 / 剧本 · 致郁思想剧",
    blurb: "适合：黑暗理想主义、悲剧。擅长：信念对撞、残酷有逻辑、改写立场的反转。",
    sort: 90,
  },
  "author-romeo": {
    role: "视觉小说 · 恋爱喜剧",
    blurb: "适合：聪明互怼恋爱、轻元梗。擅长：喜剧落回真心、闹中取静的告白节奏。",
    sort: 100,
  },
  "author-hayashi": {
    role: "视觉小说 · 温情学园",
    blurb: "适合：治愈学园日常、轻百合气息。擅长：相处厚度、缓坡感动、群像温度。",
    sort: 110,
  },
  "author-looseboy": {
    role: "视觉小说 · 现代恋爱",
    blurb: "适合：职场/成年女主恋爱。擅长：女主主体性、治愈兑账、亲密戏推进人物。",
    sort: 120,
  },
  "author-niijima": {
    role: "视觉小说 · 夏日群像",
    blurb: "适合：夏日青春、轻悬念群像。擅长：场所氛围、伏笔回收、谜题服务情感。",
    sort: 130,
  },
  "author-urushibara": {
    role: "视觉小说 · 实验哲学",
    blurb: "适合：前卫、猎奇思辨、互文实验。擅长：形式即主题、认知恐怖、多线命题。",
    sort: 140,
  },
  "author-kai": {
    role: "视觉小说 · 戏剧悬疑",
    blurb: "适合：成人情感剧、罪与秘密。擅长：慢收紧线索、关系被真相改写、克制对白。",
    sort: 150,
  },
};

export type WriterCard = {
  id: string | null;
  name: string;
  role: string;
  blurb: string;
};

export function buildWriterCards(lensCatalog: LensPackMeta[]): WriterCard[] {
  return [
    DEFAULT_WRITER,
    ...[...lensCatalog]
      .sort(
        (a, b) =>
          (WRITER_CARD_META[a.id]?.sort ?? 99) - (WRITER_CARD_META[b.id]?.sort ?? 99)
      )
      .map((p) => ({
        id: p.id as string | null,
        name: p.name,
        role: WRITER_CARD_META[p.id]?.role || "作家 · 思维包",
        blurb:
          WRITER_CARD_META[p.id]?.blurb ||
          "公开技法启发向参谋视角（非本人，禁止仿写原文）。",
      })),
  ];
}
