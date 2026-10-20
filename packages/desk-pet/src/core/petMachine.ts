/**
 * 桌宠状态机（纯函数 reducer）— 规格见 docs/mascot-pet-spec.md §2–§3。
 *
 * 只管「她现在是什么姿势、什么表情、说哪句」，不管屏幕坐标与计时：
 * 时间由事件里的 `now` 传入，随机数由 `r` 传入，方便测试。
 * 渲染层看到 body 不再是 walk 时负责停下位移。
 */
import type { PetLineKey, PetLineVars } from "./petCopy";
import { CELEBRATE_MS, FEED_TOTAL_MS, PLAY_MS } from "./petMotion";

export type PetPlacement =
  | "corner"
  | "dock"
  | "perchTop"
  | "peekOver"
  | "peekUnder"
  | "perchSideLeft"
  | "perchSideRight"
  | "edgeLeft"
  | "edgeRight"
  | "free";

export type PetBody =
  | "idle"
  | "walk"
  | "perchTop"
  | "peekOver"
  | "peekSide"
  | "hideCorner"
  | "happy"
  | "feed"
  | "play"
  | "headpat"
  | "nod"
  | "fluster"
  | "sleep"
  | "held"
  | "land";

export type PetMood = "neutral" | "happy" | "sad" | "think" | "fluster";

export type PetEmote = "dots" | "question" | "sweat" | "zzz" | "heart" | null;

export type PetAppEvent =
  | "save:ok"
  | "save:error"
  | "compile:ok"
  | "compile:error"
  | "export:ok"
  | "export:error"
  | "agent:thinking"
  | "agent:streaming"
  | "agent:done"
  | "agent:error"
  | "focus:exit";

export const PET_PRIORITY = { idle: 0, auto: 1, app: 2, user: 3, drag: 4 } as const;
type Priority = (typeof PET_PRIORITY)[keyof typeof PET_PRIORITY];

export const SLEEP_AFTER_MS = 3 * 60_000;
const SLEEP_MIN_MS = 45_000;
const SLEEP_SPREAD_MS = 75_000;
const BUBBLE_MS = 5200;
const CLICK_SPAM_WINDOW_MS = 2000;
const CLICK_SPAM_COUNT = 3;
const TYPING_QUIET_MS = 10_000;
const AGENT_SLOW_MS = 8000;
/** 思考脸挂太久会不眨眼：到点只收脸，Agent 状态仍可 thinking */
export const THINK_FACE_MAX_MS = 15_000;
/** 任意表情贴片上限；超时强制回底表情 */
export const EXPRESSION_MAX_MS = 20_000;
const MIN = 60_000;

const GROUND_POSE: ReadonlySet<PetPlacement> = new Set<PetPlacement>([
  "free",
  "corner",
  "dock",
]);

const POSE_CYCLE = ["idle", "hideCorner", "sleep"] as const;
type PoseCycleBody = (typeof POSE_CYCLE)[number];

const COOLDOWN_MS: Partial<Record<PetLineKey, number>> = {
  /** 待机写作提醒：约 2.5 分钟一句，别刷屏 */
  chatter: 2.5 * MIN,
  lateNight: 30 * MIN,
  held: MIN,
  dropPerch: MIN,
  dropPeek: MIN,
  dropEdge: MIN,
  sleepIn: 10 * MIN,
  saveOk: 10 * MIN,
  saveOkLate: 10 * MIN,
  saveError: 30_000,
  compileError: 30_000,
  compileErrorLine: 30_000,
  compileFixed: 30_000,
  exportOk: 30_000,
  exportError: 30_000,
  agentError: 30_000,
  focusExit: 10 * MIN,
};

/** 同一组共用冷却（深夜版与普通版算同一句） */
const COOLDOWN_GROUP: Partial<Record<PetLineKey, string>> = {
  saveOkLate: "saveOk",
  compileErrorLine: "compileError",
};

export interface PetBubble {
  id: number;
  key: PetLineKey;
  vars?: PetLineVars;
  until: number;
}

export interface PetReaction {
  priority: Priority;
  until: number;
  /** 喂食：起跳前 / 落地后叠 idle 咀嚼嘴 */
  chew?: boolean;
  /** 玩耍：原地 walk，关掉上下起伏 */
  inPlaceWalk?: boolean;
}

export interface PetState {
  placement: PetPlacement;
  body: PetBody;
  mood: PetMood;
  emote: PetEmote;
  /** Agent 流式回复中（渲染层在气泡打字时也会播口型） */
  talking: boolean;
  bubble: PetBubble | null;
  reaction: PetReaction | null;
  agent: "idle" | "thinking" | "streaming";
  agentThinkingSince: number | null;
  /**
   * 编译/导出反馈打断「搭档在想」时，已经走过的毫秒。
   * 非空表示计时暂停；反馈结束后从这里接着走，不重新数 8 秒。
   */
  thinkPausedMs: number | null;
  /**
   * 睡着时被报错叫醒：先睁眼，到点再播慌/难过。
   * 编译通过、导出成功不走这条。
   */
  pendingWake: {
    at: number;
    event: PetAppEvent;
    lateNight: boolean;
    line?: number;
  } | null;
  agentSlowSaid: boolean;
  /** 上次编译报错后还没通过：只有这时「编译通过」才值得庆祝 */
  compileBroken: boolean;
  sleepUntil: number | null;
  /** 最近一次和桌宠本身交互（不含打字）：决定何时打瞌睡 */
  lastPetActivity: number;
  lastTyping: number;
  clicks: number[];
  saidAt: Record<string, number>;
  nextBubbleId: number;
  reducedMotion: boolean;
  quiet: boolean;
  /** 当前表情贴片开始时刻；超时回底表情 */
  exprSince: number | null;
}

export type PetEvent =
  | { type: "tick"; now: number; r?: number }
  | { type: "click"; now: number }
  | { type: "doubleClick"; now: number }
  | { type: "dragStart"; now: number }
  | { type: "dragEnd"; now: number; zone: PetPlacement }
  | { type: "walkStart"; now: number }
  | { type: "arrive"; now: number; placement: PetPlacement }
  | { type: "mini"; now: number; body: "happy" | "hideCorner" }
  | { type: "chatter"; now: number; lateNight: boolean }
  | { type: "typing"; now: number }
  | {
      type: "menu";
      now: number;
      action:
        | "dock"
        | "corner"
        | "feed"
        | "play"
        | "poseCycle"
        | "headpat"
        | "goZone";
      /** goZone：落到框下 / 靠框等；已在该位置则只说 poseCycleBlocked */
      zone?: PetPlacement;
    }
  /** 坐着的编辑框滚出屏幕或被卸掉：回到地面待机 */
  | { type: "frameGone"; now: number }
  /** 组件台用：直接进入睡眠，好截「睡着被叫醒」 */
  | { type: "forceSleep"; now: number }
  | { type: "settings"; reducedMotion?: boolean; quiet?: boolean }
  | {
      type: "app";
      now: number;
      event: PetAppEvent;
      lateNight?: boolean;
      /** 编译报错的行号（拿得到时） */
      line?: number;
    };

export function createPetState(
  now: number,
  opts: { placement?: PetPlacement; reducedMotion?: boolean; quiet?: boolean } = {}
): PetState {
  const placement = opts.placement ?? "corner";
  return {
    placement,
    body: restBody(placement),
    mood: "neutral",
    emote: null,
    talking: false,
    bubble: null,
    reaction: null,
    agent: "idle",
    agentThinkingSince: null,
    thinkPausedMs: null,
    pendingWake: null,
    agentSlowSaid: false,
    compileBroken: false,
    sleepUntil: null,
    lastPetActivity: now,
    lastTyping: 0,
    clicks: [],
    saidAt: {},
    nextBubbleId: 1,
    reducedMotion: opts.reducedMotion ?? false,
    quiet: opts.quiet ?? false,
    exprSince: null,
  };
}

/** 每个位置对应的静止身体 */
export function restBody(placement: PetPlacement): PetBody {
  switch (placement) {
    case "perchTop":
      return "perchTop";
    case "peekOver":
    case "peekUnder":
      return "peekOver";
    case "edgeLeft":
    case "edgeRight":
      return "peekSide";
    default:
      return "idle";
  }
}

const RESTING: ReadonlySet<PetBody> = new Set<PetBody>([
  "idle",
  "perchTop",
  "peekOver",
  "peekSide",
  "hideCorner",
]);

/** 减少动画模式下不播的身体反应（跳、抖、落地、点头、喂食/玩耍图集）：只换表情 */
const MOTION_BODIES: ReadonlySet<PetBody> = new Set<PetBody>([
  "happy",
  "fluster",
  "land",
  "nod",
  "feed",
  "play",
]);

function reactionActive(s: PetState, now: number): boolean {
  return s.reaction !== null && s.reaction.until > now;
}

function canReact(s: PetState, priority: Priority, now: number): boolean {
  return !reactionActive(s, now) || priority >= (s.reaction as PetReaction).priority;
}

/** 用户主动动作播放中：不响应同类触发（拖拽仍可打断） */
function userBusy(s: PetState, now: number): boolean {
  return reactionActive(s, now) && (s.reaction as PetReaction).priority >= PET_PRIORITY.user;
}

function withBaseLook(s: PetState, now?: number): PetState {
  if (s.body === "sleep") return { ...s, mood: "neutral", emote: "zzz", exprSince: null };
  if (s.agent === "thinking") {
    const next = { ...s, mood: "think" as const, emote: "dots" as const };
    if (next.exprSince !== null) return next;
    return now !== undefined ? { ...next, exprSince: now } : next;
  }
  return { ...s, mood: "neutral", emote: null, exprSince: null };
}

function settle(s: PetState): PetState {
  return withBaseLook({ ...s, reaction: null, body: restBody(s.placement) });
}

function markExpr(s: PetState, now: number): PetState {
  const expressive = s.mood !== "neutral" || s.emote === "dots" || s.emote === "heart"
    || s.emote === "question" || s.emote === "sweat";
  if (!expressive) return { ...s, exprSince: null };
  if (s.exprSince !== null) return s;
  return { ...s, exprSince: now };
}

function wake(s: PetState, now: number): PetState {
  if (s.body !== "sleep") return s;
  return withBaseLook({
    ...s,
    body: restBody(s.placement),
    sleepUntil: null,
    lastPetActivity: now,
  });
}

type ReactionSpec = {
  body?: PetBody;
  mood: PetMood;
  emote?: PetEmote;
  ms: number;
  priority: Priority;
  chew?: boolean;
  inPlaceWalk?: boolean;
};

/** 调用方负责先判断 canReact；body 省略 = 只换表情，身体回静止姿势 */
function react(s: PetState, now: number, r: ReactionSpec): PetState {
  const wanted = r.body;
  const body =
    wanted && !(s.reducedMotion && MOTION_BODIES.has(wanted))
      ? wanted
      : restBody(s.placement);
  const reaction: PetReaction = { priority: r.priority, until: now + r.ms };
  if (r.chew) reaction.chew = true;
  if (r.inPlaceWalk) reaction.inPlaceWalk = true;
  return markExpr(
    {
      ...s,
      body,
      mood: r.mood,
      emote: r.emote ?? null,
      reaction,
      sleepUntil: null,
    },
    now
  );
}

/** 编译/导出真的播出来才暂停思考计时；被更高优先级挡住就当没按过 */
function feedback(
  s: PetState,
  now: number,
  r: ReactionSpec,
  key: PetLineKey | null,
  vars?: PetLineVars
): PetState {
  const paused = pauseThink(s, now);
  const next = reactAndSay(paused, now, r, key, vars);
  if (next.reaction === paused.reaction) return { ...next, thinkPausedMs: s.thinkPausedMs };
  return next;
}

function say(s: PetState, now: number, key: PetLineKey, vars?: PetLineVars): PetState {
  if (s.quiet) return s;
  const group = COOLDOWN_GROUP[key] ?? key;
  const cooldown = COOLDOWN_MS[key] ?? 0;
  const last = s.saidAt[group];
  if (cooldown > 0 && last !== undefined && now - last < cooldown) return s;
  return {
    ...s,
    bubble: { id: s.nextBubbleId, key, vars, until: now + BUBBLE_MS },
    nextBubbleId: s.nextBubbleId + 1,
    saidAt: { ...s.saidAt, [group]: now },
  };
}

function reactAndSay(
  s: PetState,
  now: number,
  r: ReactionSpec,
  key: PetLineKey | null,
  vars?: PetLineVars
): PetState {
  if (!canReact(s, r.priority, now)) return s;
  const n = react(s, now, r);
  return key ? say(n, now, key, vars) : n;
}

function canFallAsleep(s: PetState, now: number): boolean {
  return (
    RESTING.has(s.body) &&
    !reactionActive(s, now) &&
    s.agent === "idle" &&
    s.placement !== "edgeLeft" &&
    s.placement !== "edgeRight" &&
    now - s.lastPetActivity >= SLEEP_AFTER_MS
  );
}

const WAKE_EYES_MS = 300;

function pauseThink(s: PetState, now: number): PetState {
  if (s.agent !== "thinking" || s.agentThinkingSince === null || s.thinkPausedMs !== null) return s;
  return { ...s, thinkPausedMs: Math.max(0, now - s.agentThinkingSince) };
}

function resumeThink(s: PetState, now: number): PetState {
  if (s.thinkPausedMs === null) return s;
  return {
    ...s,
    thinkPausedMs: null,
    agentThinkingSince: now - s.thinkPausedMs,
  };
}

/** 用户把她拖走或拍醒时，排队的叫醒不再补播 */
function cancelPendingWake(s: PetState, now: number): PetState {
  if (!s.pendingWake) return s;
  return resumeThink({ ...s, pendingWake: null }, now);
}

function tick(s: PetState, now: number, r: number): PetState {
  let n = s;
  if (n.bubble && n.bubble.until <= now) n = { ...n, bubble: null };
  if (n.pendingWake && n.pendingWake.at <= now) {
    const p = n.pendingWake;
    n = applyApp({ ...n, pendingWake: null }, now, p.event, p.lateNight, p.line);
  }
  if (n.reaction && n.reaction.until <= now) n = settle(n);
  if (n.thinkPausedMs !== null && n.pendingWake === null && !reactionActive(n, now)) {
    n = resumeThink(n, now);
  }
  if (n.body === "sleep" && n.sleepUntil !== null && n.sleepUntil <= now) {
    n = say(wake(n, now), now, "wake");
  }
  if (
    n.agent === "thinking" &&
    n.body !== "sleep" &&
    n.thinkPausedMs === null &&
    !n.agentSlowSaid &&
    n.agentThinkingSince !== null &&
    now - n.agentThinkingSince >= AGENT_SLOW_MS
  ) {
    n = { ...say(n, now, "agentSlow"), agentSlowSaid: true };
  }
  if (
    n.agent === "thinking" &&
    n.thinkPausedMs === null &&
    n.agentThinkingSince !== null &&
    now - n.agentThinkingSince >= THINK_FACE_MAX_MS &&
    (n.mood === "think" || n.emote === "dots")
  ) {
    n = { ...n, mood: "neutral", emote: null, exprSince: null };
  }
  if (
    n.exprSince !== null &&
    now - n.exprSince >= EXPRESSION_MAX_MS &&
    (n.mood !== "neutral" || (n.emote !== null && n.emote !== "zzz"))
  ) {
    n = settle(n);
  }
  if (canFallAsleep(n, now)) {
    n = say(
      {
        ...n,
        body: "sleep",
        mood: "neutral",
        emote: "zzz",
        sleepUntil: now + SLEEP_MIN_MS + r * SLEEP_SPREAD_MS,
      },
      now,
      "sleepIn"
    );
  }
  return n;
}

function onClick(s: PetState, now: number): PetState {
  if (s.body === "held") return s;
  const n = cancelPendingWake({ ...s, lastPetActivity: now }, now);
  if (n.body === "sleep") return say(wake(n, now), now, "wake");
  if (n.placement === "edgeLeft" || n.placement === "edgeRight") {
    if (userBusy(n, now)) return n;
    return reactAndSay(
      { ...n, placement: "free" },
      now,
      { body: "happy", mood: "happy", ms: CELEBRATE_MS, priority: PET_PRIORITY.user },
      "spotted"
    );
  }
  // 连点计数在播放锁定期间也累计，满 3 次可升级成 poke
  const clicks = [...n.clicks.filter((t) => now - t < CLICK_SPAM_WINDOW_MS), now];
  if (clicks.length >= CLICK_SPAM_COUNT) {
    return reactAndSay(
      { ...n, clicks: [] },
      now,
      {
        body: "fluster",
        mood: "fluster",
        emote: "sweat",
        ms: 700,
        priority: PET_PRIORITY.user,
      },
      "poke"
    );
  }
  if (userBusy(n, now)) return { ...n, clicks };
  return reactAndSay(
    { ...n, clicks },
    now,
    { body: "nod", mood: "happy", ms: 600, priority: PET_PRIORITY.user },
    "click"
  );
}

function onDoubleClick(s: PetState, now: number): PetState {
  if (s.body === "held") return s;
  const n = { ...s, lastPetActivity: now, clicks: [] };
  if (n.body === "sleep") return say(wake(n, now), now, "wake");
  if (userBusy(n, now)) return n;
  return reactAndSay(
    n,
    now,
    {
      body: "headpat",
      mood: "happy",
      emote: "heart",
      ms: 1000,
      priority: PET_PRIORITY.user,
    },
    "headpat"
  );
}

const DROP_LINE: Partial<Record<PetPlacement, PetLineKey>> = {
  perchTop: "dropPerch",
  peekOver: "dropPeek",
  peekUnder: "dropPeek",
  perchSideLeft: "dropEdge",
  perchSideRight: "dropEdge",
  edgeLeft: "dropEdge",
  edgeRight: "dropEdge",
};

function onDragEnd(s: PetState, now: number, zone: PetPlacement): PetState {
  const n: PetState = { ...s, placement: zone, reaction: null, lastPetActivity: now };
  if (zone === "free") {
    return react(n, now, {
      body: "land",
      mood: "neutral",
      ms: 320,
      priority: PET_PRIORITY.user,
    });
  }
  const placed = withBaseLook({ ...n, body: restBody(zone) }, now);
  const key = DROP_LINE[zone];
  return key ? say(placed, now, key) : placed;
}

function currentPoseCycleBody(s: PetState): PoseCycleBody {
  if (s.body === "hideCorner" || s.body === "sleep") return s.body;
  return "idle";
}

function onMenu(
  s: PetState,
  now: number,
  action:
    | "dock"
    | "corner"
    | "feed"
    | "play"
    | "poseCycle"
    | "headpat"
    | "goZone",
  zone?: PetPlacement
): PetState {
  if (action === "dock") {
    if (userBusy(s, now)) return s;
    return withBaseLook(
      {
        ...s,
        placement: "dock",
        body: "idle",
        reaction: null,
        sleepUntil: null,
        lastPetActivity: now,
      },
      now
    );
  }
  if (action === "corner") {
    if (userBusy(s, now)) return s;
    return react({ ...s, placement: "corner", lastPetActivity: now }, now, {
      body: "hideCorner",
      mood: "neutral",
      ms: 900,
      priority: PET_PRIORITY.user,
    });
  }
  if (userBusy(s, now)) return s;
  const base = { ...s, lastPetActivity: now };
  if (action === "feed") {
    return reactAndSay(
      base,
      now,
      {
        body: "feed",
        mood: "happy",
        emote: "heart",
        ms: FEED_TOTAL_MS,
        priority: PET_PRIORITY.user,
      },
      "feed"
    );
  }
  if (action === "play") {
    return reactAndSay(
      base,
      now,
      {
        body: "play",
        mood: "happy",
        emote: "dots",
        ms: PLAY_MS,
        priority: PET_PRIORITY.user,
      },
      "play"
    );
  }
  if (action === "headpat") {
    return onDoubleClick(base, now);
  }
  if (action === "poseCycle") {
    if (!GROUND_POSE.has(base.placement)) {
      return say(base, now, "poseCycleBlocked");
    }
    const cur = currentPoseCycleBody(base);
    const idx = POSE_CYCLE.indexOf(cur);
    const next = POSE_CYCLE[(idx + 1) % POSE_CYCLE.length];
    if (next === "idle") {
      return say(
        withBaseLook(
          { ...base, body: "idle", reaction: null, sleepUntil: null },
          now
        ),
        now,
        "poseCycle"
      );
    }
    if (next === "hideCorner") {
      return say(
        {
          ...base,
          body: "hideCorner",
          mood: "neutral",
          emote: null,
          reaction: null,
          sleepUntil: null,
          exprSince: null,
        },
        now,
        "poseCycle"
      );
    }
    return say(
      {
        ...base,
        body: "sleep",
        mood: "neutral",
        emote: "zzz",
        reaction: null,
        sleepUntil: now + 60 * 60 * 1000,
        exprSince: null,
      },
      now,
      "poseCycle"
    );
  }
  // goZone
  if (!zone) return s;
  if (base.placement === zone) return say(base, now, "poseCycleBlocked");
  const line =
    zone === "peekUnder" ? "menuPeekUnder" : zone === "perchSideLeft" || zone === "perchSideRight"
      ? "menuPerchSide"
      : null;
  const placed = withBaseLook(
    {
      ...base,
      placement: zone,
      body: restBody(zone),
      reaction: null,
      sleepUntil: null,
    },
    now
  );
  return line ? say(placed, now, line) : placed;
}

function onApp(
  s: PetState,
  now: number,
  event: PetAppEvent,
  lateNight: boolean,
  line: number | undefined
): PetState {
  const knownLine = line !== undefined && line >= 1 ? line : undefined;
  const asleep = s.body === "sleep";
  const wakeFirst =
    asleep &&
    (event === "compile:error" || event === "export:error" || event === "agent:error");
  if (wakeFirst) {
    const opened = withBaseLook({
      ...pauseThink(s, now),
      body: restBody(s.placement),
      sleepUntil: null,
      lastPetActivity: now,
    });
    return {
      ...opened,
      pendingWake: { at: now + WAKE_EYES_MS, event, lateNight, line: knownLine },
    };
  }
  return applyApp(s, now, event, lateNight, knownLine);
}

function applyApp(
  s: PetState,
  now: number,
  event: PetAppEvent,
  lateNight: boolean,
  line: number | undefined
): PetState {
  const asleep = s.body === "sleep";
  const app = PET_PRIORITY.app;
  const knownLine = line !== undefined && line >= 1 ? line : undefined;
  switch (event) {
    case "agent:thinking": {
      const n: PetState = {
        ...s,
        agent: "thinking",
        agentThinkingSince: now,
        thinkPausedMs: null,
        agentSlowSaid: false,
        talking: false,
        exprSince: null,
      };
      return reactionActive(n, now) ? n : withBaseLook(n, now);
    }
    case "agent:streaming": {
      const n: PetState = {
        ...s,
        agent: "streaming",
        agentThinkingSince: null,
        thinkPausedMs: null,
        talking: true,
      };
      return reactionActive(n, now) ? n : withBaseLook(n, now);
    }
    case "agent:done": {
      const n: PetState = {
        ...s,
        agent: "idle",
        agentThinkingSince: null,
        thinkPausedMs: null,
        talking: false,
      };
      if (asleep) return n;
      return reactAndSay(
        n,
        now,
        { body: "nod", mood: "neutral", ms: 600, priority: app },
        null
      );
    }
    case "agent:error": {
      const n = wake(
        { ...s, agent: "idle", agentThinkingSince: null, thinkPausedMs: null, talking: false },
        now
      );
      return reactAndSay(
        n,
        now,
        { mood: "sad", emote: "sweat", ms: 1500, priority: app },
        "agentError"
      );
    }
    case "save:ok":
      if (asleep) return s;
      return reactAndSay(
        s,
        now,
        { body: "nod", mood: "happy", ms: 600, priority: app },
        lateNight ? "saveOkLate" : "saveOk"
      );
    case "save:error":
      return reactAndSay(
        wake(s, now),
        now,
        { mood: "sad", emote: "sweat", ms: 1500, priority: app },
        "saveError"
      );
    case "compile:error":
      return feedback(
        wake({ ...s, compileBroken: true }, now),
        now,
        { body: "fluster", mood: "fluster", emote: "question", ms: 900, priority: app },
        knownLine === undefined ? "compileError" : "compileErrorLine",
        knownLine === undefined ? undefined : { line: knownLine }
      );
    case "compile:ok": {
      if (!s.compileBroken) return s;
      const n = { ...s, compileBroken: false };
      if (asleep) return n;
      return feedback(
        n,
        now,
        { body: "happy", mood: "happy", ms: CELEBRATE_MS, priority: app },
        "compileFixed"
      );
    }
    case "export:ok":
      if (asleep) return s;
      return feedback(
        s,
        now,
        { body: "happy", mood: "happy", emote: "heart", ms: CELEBRATE_MS, priority: app },
        "exportOk"
      );
    case "export:error":
      return feedback(
        wake(s, now),
        now,
        { mood: "sad", ms: 1500, priority: app },
        "exportError"
      );
    case "focus:exit":
      if (asleep) return s;
      return reactAndSay(
        s,
        now,
        { body: "happy", mood: "happy", ms: CELEBRATE_MS, priority: app },
        "focusExit"
      );
  }
}

export function petReducer(s: PetState, e: PetEvent): PetState {
  switch (e.type) {
    case "tick":
      return tick(s, e.now, e.r ?? 0.5);
    case "click":
      return onClick(s, e.now);
    case "doubleClick":
      return onDoubleClick(s, e.now);
    case "dragStart":
      return say(
        {
          ...cancelPendingWake(s, e.now),
          body: "held",
          mood: "fluster",
          emote: null,
          reaction: { priority: PET_PRIORITY.drag, until: Number.POSITIVE_INFINITY },
          sleepUntil: null,
          clicks: [],
          lastPetActivity: e.now,
        },
        e.now,
        "held"
      );
    case "dragEnd":
      return onDragEnd(s, e.now, e.zone);
    case "walkStart":
      if (
        s.reducedMotion ||
        s.body === "sleep" ||
        s.body === "held" ||
        reactionActive(s, e.now)
      ) {
        return s;
      }
      return { ...s, body: "walk" };
    case "arrive":
      return {
        ...s,
        placement: e.placement,
        body: s.body === "walk" ? restBody(e.placement) : s.body,
      };
    case "mini":
      if (s.reducedMotion || !RESTING.has(s.body) || reactionActive(s, e.now)) return s;
      return react(s, e.now, {
        body: e.body,
        mood: e.body === "happy" ? "happy" : "neutral",
        ms: 2500,
        priority: PET_PRIORITY.auto,
      });
    case "chatter":
      if (
        !RESTING.has(s.body) ||
        reactionActive(s, e.now) ||
        e.now - s.lastTyping < TYPING_QUIET_MS
      ) {
        return s;
      }
      return say(s, e.now, e.lateNight ? "lateNight" : "chatter");
    case "typing":
      return { ...s, lastTyping: e.now };
    case "frameGone":
      return withBaseLook({
        ...s,
        placement: "free",
        body: "idle",
        reaction: null,
        sleepUntil: null,
        lastPetActivity: e.now,
      });
    case "menu":
      return onMenu(s, e.now, e.action, e.zone);
    case "forceSleep":
      return {
        ...s,
        body: "sleep",
        mood: "neutral",
        emote: "zzz",
        reaction: null,
        pendingWake: null,
        talking: false,
        sleepUntil: e.now + 60 * 60 * 1000,
      };
    case "settings": {
      const reducedMotion = e.reducedMotion ?? s.reducedMotion;
      const quiet = e.quiet ?? s.quiet;
      return {
        ...s,
        reducedMotion,
        quiet,
        bubble: quiet ? null : s.bubble,
        body: reducedMotion && s.body === "walk" ? restBody(s.placement) : s.body,
      };
    }
    case "app":
      return onApp(s, e.now, e.event, e.lateNight ?? false, e.line);
  }
}
