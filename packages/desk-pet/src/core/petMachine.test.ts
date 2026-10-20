import { describe, expect, it } from "vitest";
import { petLine, petLinePool, petLineTotal } from "./petCopy";
import {
  SLEEP_AFTER_MS,
  createPetState,
  petReducer,
  type PetEvent,
  type PetState,
} from "./petMachine";

const T0 = 1_000_000;

function run(s: PetState, ...events: PetEvent[]): PetState {
  return events.reduce(petReducer, s);
}

describe("petMachine", () => {
  it("starts resting at the placement's rest body", () => {
    expect(createPetState(T0).body).toBe("idle");
    expect(createPetState(T0, { placement: "perchTop" }).body).toBe("perchTop");
    expect(createPetState(T0, { placement: "edgeRight" }).body).toBe("peekSide");
  });

  it("click nods with a line, then settles back after the reaction expires", () => {
    const s = run(createPetState(T0), { type: "click", now: T0 });
    expect(s.body).toBe("nod");
    expect(s.mood).toBe("happy");
    expect(s.bubble?.key).toBe("click");
    const later = run(s, { type: "tick", now: T0 + 700 });
    expect(later.body).toBe("idle");
    expect(later.mood).toBe("neutral");
  });

  it("three clicks within 2s turn into a fluster poke", () => {
    const s = run(
      createPetState(T0),
      { type: "click", now: T0 },
      { type: "click", now: T0 + 700 },
      { type: "click", now: T0 + 1400 }
    );
    expect(s.body).toBe("fluster");
    expect(s.emote).toBe("sweat");
    expect(s.bubble?.key).toBe("poke");
    expect(s.clicks).toEqual([]);
  });

  it("clicks spread out over more than 2s do not count as poking", () => {
    const s = run(
      createPetState(T0),
      { type: "click", now: T0 },
      { type: "click", now: T0 + 2100 },
      { type: "click", now: T0 + 4200 }
    );
    expect(s.body).toBe("nod");
  });

  it("drag holds her above every other priority until dropped", () => {
    let s = run(createPetState(T0), { type: "dragStart", now: T0 });
    expect(s.body).toBe("held");
    s = run(
      s,
      { type: "app", now: T0 + 10, event: "export:ok" },
      { type: "tick", now: T0 + 60_000 }
    );
    expect(s.body).toBe("held");
    s = run(s, { type: "dragEnd", now: T0 + 60_010, zone: "perchTop" });
    expect(s.placement).toBe("perchTop");
    expect(s.body).toBe("perchTop");
    expect(s.bubble?.key).toBe("dropPerch");
  });

  it("dropping under the frame or against its side keeps those placements", () => {
    const under = run(createPetState(T0), { type: "dragEnd", now: T0, zone: "peekUnder" });
    expect(under.placement).toBe("peekUnder");
    expect(under.body).toBe("peekOver");
    expect(under.bubble?.key).toBe("dropPeek");
    const side = run(createPetState(T0), { type: "dragEnd", now: T0, zone: "perchSideLeft" });
    expect(side.placement).toBe("perchSideLeft");
    expect(side.body).toBe("idle");
    expect(side.bubble?.key).toBe("dropEdge");
  });

  it("leaves the frame for an idle stance when the editor goes away", () => {
    const perched = run(createPetState(T0, { placement: "perchTop" }), {
      type: "frameGone",
      now: T0 + 10,
    });
    expect(perched.placement).toBe("free");
    expect(perched.body).toBe("idle");
    expect(perched.mood).toBe("neutral");
    expect(perched.emote).toBeNull();
    const asleep = run(
      { ...createPetState(T0, { placement: "perchTop" }), body: "sleep", emote: "zzz", sleepUntil: T0 + 999 },
      { type: "frameGone", now: T0 + 10 }
    );
    expect(asleep.body).toBe("idle");
    expect(asleep.emote).toBeNull();
    expect(asleep.sleepUntil).toBeNull();
  });

  it("dropping on free space plays a landing, then rests", () => {
    let s = run(
      createPetState(T0),
      { type: "dragStart", now: T0 },
      { type: "dragEnd", now: T0 + 500, zone: "free" }
    );
    expect(s.body).toBe("land");
    s = run(s, { type: "tick", now: T0 + 900 });
    expect(s.body).toBe("idle");
    expect(s.placement).toBe("free");
  });

  it("clicking her at a screen edge pops her out with 'spotted'", () => {
    const s = run(createPetState(T0, { placement: "edgeLeft" }), {
      type: "click",
      now: T0,
    });
    expect(s.placement).toBe("free");
    expect(s.body).toBe("happy");
    expect(s.bubble?.key).toBe("spotted");
  });

  it("app reactions cannot interrupt a higher-priority user reaction", () => {
    const s = run(
      createPetState(T0),
      { type: "doubleClick", now: T0 },
      { type: "app", now: T0 + 100, event: "save:ok" }
    );
    expect(s.body).toBe("headpat");
    expect(s.bubble?.key).toBe("headpat");
  });

  it("user reactions interrupt app reactions", () => {
    const s = run(
      createPetState(T0),
      { type: "app", now: T0, event: "save:error" },
      { type: "click", now: T0 + 100 }
    );
    expect(s.body).toBe("nod");
    expect(s.bubble?.key).toBe("click");
  });

  it("save:ok only speaks once per 10 minutes but always nods", () => {
    let s = run(createPetState(T0), { type: "app", now: T0, event: "save:ok" });
    expect(s.bubble?.key).toBe("saveOk");
    const firstId = s.bubble?.id;
    s = run(s, { type: "app", now: T0 + 60_000, event: "save:ok" });
    expect(s.body).toBe("nod");
    expect(s.bubble?.id).toBe(firstId);
    s = run(s, {
      type: "app",
      now: T0 + 10 * 60_000 + 1,
      event: "save:ok",
      lateNight: true,
    });
    expect(s.bubble?.key).toBe("saveOkLate");
  });

  it("late-night save shares the save cooldown", () => {
    let s = run(createPetState(T0), {
      type: "app",
      now: T0,
      event: "save:ok",
      lateNight: true,
    });
    expect(s.bubble?.key).toBe("saveOkLate");
    s = run(
      s,
      { type: "tick", now: T0 + 6000 },
      { type: "app", now: T0 + 7000, event: "save:ok" }
    );
    expect(s.bubble).toBeNull();
  });

  it("compile error mentions the line when known; fix is celebrated only after an error", () => {
    let s = run(createPetState(T0), { type: "app", now: T0, event: "compile:ok" });
    expect(s.body).toBe("idle");
    expect(s.bubble).toBeNull();
    s = run(s, { type: "app", now: T0 + 10, event: "compile:error", line: 42 });
    expect(s.body).toBe("fluster");
    expect(s.emote).toBe("question");
    expect(s.bubble?.key).toBe("compileErrorLine");
    expect(s.bubble?.vars).toEqual({ line: 42 });
    s = run(
      s,
      { type: "tick", now: T0 + 1000 },
      { type: "app", now: T0 + 2000, event: "compile:ok" }
    );
    expect(s.body).toBe("happy");
    expect(s.bubble?.key).toBe("compileFixed");
    expect(s.compileBroken).toBe(false);
  });

  it("agent thinking shows the think face, speaks after 8s, talking while streaming", () => {
    let s = run(createPetState(T0), { type: "app", now: T0, event: "agent:thinking" });
    expect(s.mood).toBe("think");
    expect(s.emote).toBe("dots");
    expect(s.bubble).toBeNull();
    s = run(s, { type: "tick", now: T0 + 7999 });
    expect(s.bubble).toBeNull();
    s = run(s, { type: "tick", now: T0 + 8000 });
    expect(s.bubble?.key).toBe("agentSlow");
    const slowId = s.bubble?.id;
    s = run(s, { type: "tick", now: T0 + 9000 });
    expect(s.bubble?.id).toBe(slowId);
    s = run(s, { type: "app", now: T0 + 9500, event: "agent:streaming" });
    expect(s.talking).toBe(true);
    expect(s.mood).toBe("neutral");
    expect(s.emote).toBeNull();
    s = run(s, { type: "app", now: T0 + 12_000, event: "agent:done" });
    expect(s.talking).toBe(false);
    expect(s.body).toBe("nod");
    expect(s.agent).toBe("idle");
  });

  it("agent error makes her sad and refers to the agent as 搭档", () => {
    const s = run(
      createPetState(T0),
      { type: "app", now: T0, event: "agent:thinking" },
      { type: "app", now: T0 + 100, event: "agent:error" }
    );
    expect(s.mood).toBe("sad");
    expect(s.bubble?.key).toBe("agentError");
    expect(petLine("agentError")).toContain("搭档");
  });

  it("a reaction ending during agent thinking returns to the think face", () => {
    const s = run(
      createPetState(T0),
      { type: "app", now: T0, event: "agent:thinking" },
      { type: "click", now: T0 + 10 },
      { type: "tick", now: T0 + 700 }
    );
    expect(s.mood).toBe("think");
    expect(s.emote).toBe("dots");
  });

  it("falls asleep after 3 minutes without pet interaction and wakes on her own", () => {
    let s = run(createPetState(T0), { type: "tick", now: T0 + SLEEP_AFTER_MS - 1 });
    expect(s.body).toBe("idle");
    s = run(s, { type: "tick", now: T0 + SLEEP_AFTER_MS, r: 0 });
    expect(s.body).toBe("sleep");
    expect(s.emote).toBe("zzz");
    expect(s.sleepUntil).toBe(T0 + SLEEP_AFTER_MS + 45_000);
    s = run(s, { type: "tick", now: T0 + SLEEP_AFTER_MS + 45_000 });
    expect(s.body).toBe("idle");
    expect(s.bubble?.key).toBe("wake");
  });

  it("typing does not keep her awake, but does keep her quiet", () => {
    let s = run(
      createPetState(T0),
      { type: "typing", now: T0 + SLEEP_AFTER_MS - 10 },
      { type: "chatter", now: T0 + SLEEP_AFTER_MS - 5, lateNight: false }
    );
    expect(s.bubble).toBeNull();
    s = run(s, { type: "tick", now: T0 + SLEEP_AFTER_MS });
    expect(s.body).toBe("sleep");
  });

  it("does not fall asleep at a screen edge or while the agent is busy", () => {
    const edge = run(createPetState(T0, { placement: "edgeRight" }), {
      type: "tick",
      now: T0 + SLEEP_AFTER_MS,
    });
    expect(edge.body).toBe("peekSide");
    const busy = run(
      createPetState(T0),
      { type: "app", now: T0, event: "agent:streaming" },
      { type: "tick", now: T0 + SLEEP_AFTER_MS }
    );
    expect(busy.body).toBe("idle");
  });

  it("while asleep, good news is ignored but errors wake her", () => {
    const asleep = run(createPetState(T0), { type: "tick", now: T0 + SLEEP_AFTER_MS });
    expect(
      run(asleep, { type: "app", now: asleep.lastPetActivity, event: "save:ok" }).body
    ).toBe("sleep");
    const woke = run(asleep, {
      type: "app",
      now: T0 + SLEEP_AFTER_MS + 10,
      event: "save:error",
    });
    expect(woke.body).toBe("idle");
    expect(woke.mood).toBe("sad");
    expect(woke.bubble?.key).toBe("saveError");
  });

  it("clicking a sleeping pet wakes her with a line", () => {
    const s = run(
      createPetState(T0),
      { type: "tick", now: T0 + SLEEP_AFTER_MS },
      { type: "click", now: T0 + SLEEP_AFTER_MS + 100 }
    );
    expect(s.body).toBe("idle");
    expect(s.bubble?.key).toBe("wake");
  });

  it("quiet mode keeps the animation but never shows a bubble", () => {
    const s = run(createPetState(T0, { quiet: true }), {
      type: "doubleClick",
      now: T0,
    });
    expect(s.body).toBe("headpat");
    expect(s.bubble).toBeNull();
    const toggled = run(
      createPetState(T0),
      { type: "click", now: T0 },
      { type: "settings", quiet: true }
    );
    expect(toggled.bubble).toBeNull();
  });

  it("reduced motion blocks walking and autonomous mini actions", () => {
    let s = createPetState(T0, { reducedMotion: true });
    s = run(
      s,
      { type: "walkStart", now: T0 },
      { type: "mini", now: T0, body: "happy" }
    );
    expect(s.body).toBe("idle");
    const walking = run(createPetState(T0), { type: "walkStart", now: T0 });
    expect(walking.body).toBe("walk");
    expect(run(walking, { type: "settings", reducedMotion: true }).body).toBe("idle");
  });

  it("reduced motion keeps reactions to a face change on a still pose", () => {
    const rm = createPetState(T0, { reducedMotion: true });
    const cheered = run(rm, { type: "app", now: T0, event: "export:ok" });
    expect(cheered.body).toBe("idle");
    expect(cheered.mood).toBe("happy");
    expect(cheered.emote).toBe("heart");
    expect(cheered.bubble?.key).toBe("exportOk");
    // 被摸头是静态姿势，不在 MOTION_BODIES 里
    expect(run(rm, { type: "doubleClick", now: T0 }).body).toBe("headpat");
    const poked = run(
      rm,
      { type: "click", now: T0 },
      { type: "click", now: T0 + 100 },
      { type: "click", now: T0 + 200 }
    );
    expect(poked.body).toBe("idle");
    expect(poked.mood).toBe("fluster");
    const dropped = run(
      rm,
      { type: "dragStart", now: T0 },
      { type: "dragEnd", now: T0 + 500, zone: "free" }
    );
    expect(dropped.body).toBe("idle");
    const perched = run(
      createPetState(T0, { placement: "perchTop", reducedMotion: true }),
      {
        type: "click",
        now: T0,
      }
    );
    expect(perched.body).toBe("perchTop");
  });

  it("walking arrives at the target's rest body; a reaction interrupts the walk", () => {
    const arrived = run(
      createPetState(T0),
      { type: "walkStart", now: T0 },
      { type: "arrive", now: T0 + 3000, placement: "peekOver" }
    );
    expect(arrived.body).toBe("peekOver");
    const interrupted = run(
      createPetState(T0),
      { type: "walkStart", now: T0 },
      { type: "app", now: T0 + 100, event: "export:ok" }
    );
    expect(interrupted.body).toBe("happy");
  });

  it("chatter respects its cooldown and the late-night pool", () => {
    let s = run(createPetState(T0), {
      type: "chatter",
      now: T0 + 20_000,
      lateNight: false,
    });
    expect(s.bubble?.key).toBe("chatter");
    const id = s.bubble?.id;
    // 2.5 分钟冷却内：普通闲聊不再换句
    s = run(s, { type: "chatter", now: T0 + 80_000, lateNight: false });
    expect(s.bubble?.id).toBe(id);
    s = run(s, { type: "chatter", now: T0 + 80_000, lateNight: true });
    expect(s.bubble?.key).toBe("lateNight");
    // 冷却过后可以再闲聊
    s = run(s, { type: "chatter", now: T0 + 20_000 + 2.5 * 60_000 + 1, lateNight: false });
    expect(s.bubble?.key).toBe("chatter");
    expect(s.bubble?.id).not.toBe(id);
  });

  it("menu: dock resets to idle, corner curls up then rests", () => {
    let s = run(createPetState(T0, { placement: "free" }), {
      type: "menu",
      now: T0,
      action: "corner",
    });
    expect(s.placement).toBe("corner");
    expect(s.body).toBe("hideCorner");
    // 蜷坐播放中锁定：dock 要等反应结束
    s = run(s, { type: "menu", now: T0 + 100, action: "dock" });
    expect(s.placement).toBe("corner");
    s = run(s, { type: "tick", now: T0 + 900 }, { type: "menu", now: T0 + 901, action: "dock" });
    expect(s.placement).toBe("dock");
    expect(s.body).toBe("idle");
    expect(s.reaction).toBeNull();
  });

  it("compile error with no line, or line 0, uses the fallback and never an empty number", () => {
    for (const line of [undefined, 0] as const) {
      const s = run(createPetState(T0), {
        type: "app",
        now: T0,
        event: "compile:error",
        line,
      });
      expect(s.bubble?.key).toBe("compileError");
      expect(s.bubble?.vars).toBeUndefined();
      expect(petLinePool("compileError")).toContain("编译卡住了，我们看看。");
      expect(petLine("compileError", {}, 0)).toBe("编译卡住了，我们看看。");
    }
  });

  it("export failure and export success keep separate cooldowns", () => {
    let s = run(createPetState(T0), { type: "app", now: T0, event: "export:error" });
    expect(s.bubble?.key).toBe("exportError");
    s = run(s, { type: "app", now: T0 + 1000, event: "export:ok" });
    expect(s.body).toBe("happy");
    expect(s.emote).toBe("heart");
    expect(s.bubble?.key).toBe("exportOk");
  });

  it("asleep compile error opens the eyes for 300ms before fluster", () => {
    let s = run(createPetState(T0), { type: "forceSleep", now: T0 });
    expect(s.body).toBe("sleep");
    s = run(s, { type: "app", now: T0 + 10, event: "compile:error", line: 7 });
    expect(s.body).toBe("idle");
    expect(s.mood).toBe("neutral");
    expect(s.emote).toBeNull();
    expect(s.bubble).toBeNull();
    s = run(s, { type: "tick", now: T0 + 309 });
    expect(s.mood).toBe("neutral");
    s = run(s, { type: "tick", now: T0 + 310 });
    expect(s.body).toBe("fluster");
    expect(s.mood).toBe("fluster");
    expect(s.emote).toBe("question");
    expect(s.bubble?.key).toBe("compileErrorLine");
    expect(s.bubble?.vars).toEqual({ line: 7 });
  });

  it("compile or export during thinking pauses the 8s clock and resumes the remainder", () => {
    let s = run(createPetState(T0), { type: "app", now: T0, event: "agent:thinking" });
    s = run(s, { type: "app", now: T0 + 3000, event: "compile:error", line: 3 });
    expect(s.thinkPausedMs).toBe(3000);
    expect(s.mood).toBe("fluster");
    s = run(s, { type: "tick", now: T0 + 3899 });
    expect(s.bubble?.key).not.toBe("agentSlow");
    expect(s.thinkPausedMs).toBe(3000);
    s = run(s, { type: "tick", now: T0 + 3900 });
    expect(s.thinkPausedMs).toBeNull();
    expect(s.agentThinkingSince).toBe(T0 + 900);
    expect(s.bubble?.key).not.toBe("agentSlow");
    s = run(s, { type: "tick", now: T0 + 3900 + 4999 });
    expect(s.bubble?.key).not.toBe("agentSlow");
    s = run(s, { type: "tick", now: T0 + 3900 + 5000 });
    expect(s.bubble?.key).toBe("agentSlow");
  });

  it("tick returns the same object when nothing changes (lets React bail out)", () => {
    const s = createPetState(T0);
    expect(petReducer(s, { type: "tick", now: T0 + 1000 })).toBe(s);
  });

  it("user menu actions lock while playing, then work again with no time cooldown", () => {
    let s = run(createPetState(T0), { type: "menu", now: T0, action: "feed" });
    expect(s.body).toBe("feed");
    expect(s.emote).toBe("heart");
    expect(s.bubble?.key).toBe("feed");
    const during = run(s, { type: "menu", now: T0 + 200, action: "play" });
    expect(during.emote).toBe("heart");
    expect(during.bubble?.key).toBe("feed");
    s = run(s, { type: "tick", now: T0 + 1520 });
    s = run(s, { type: "menu", now: T0 + 1521, action: "play" });
    expect(s.body).toBe("play");
    expect(s.emote).toBe("dots");
    expect(s.bubble?.key).toBe("play");
  });

  it("pose cycle on the frame only says blocked; on the ground rotates idle→curl→sleep", () => {
    const blocked = run(createPetState(T0, { placement: "perchTop" }), {
      type: "menu",
      now: T0,
      action: "poseCycle",
    });
    expect(blocked.bubble?.key).toBe("poseCycleBlocked");
    expect(blocked.body).toBe("perchTop");
    let s = run(createPetState(T0), { type: "menu", now: T0, action: "poseCycle" });
    expect(s.body).toBe("hideCorner");
    expect(s.bubble?.key).toBe("poseCycle");
    s = run(s, { type: "menu", now: T0 + 10, action: "poseCycle" });
    expect(s.body).toBe("sleep");
    s = run(s, { type: "menu", now: T0 + 20, action: "poseCycle" });
    expect(s.body).toBe("idle");
  });

  it("think face clears after 15s while agent may still be thinking", () => {
    let s = run(createPetState(T0), { type: "app", now: T0, event: "agent:thinking" });
    expect(s.mood).toBe("think");
    s = run(s, { type: "tick", now: T0 + 14_999 });
    expect(s.mood).toBe("think");
    s = run(s, { type: "tick", now: T0 + 15_000 });
    expect(s.mood).toBe("neutral");
    expect(s.emote).toBeNull();
    expect(s.agent).toBe("thinking");
  });
});

describe("petCopy", () => {
  it("fills the compile error line number", () => {
    expect(petLine("compileErrorLine", { line: 42 }, 0)).toBe("第 42 行好像不太对。");
  });

  it("keeps every line short enough for one bubble", () => {
    const keys = [
      "chatter",
      "lateNight",
      "click",
      "poke",
      "headpat",
      "held",
      "dropPerch",
      "dropPeek",
      "dropEdge",
      "spotted",
      "sleepIn",
      "wake",
      "saveOk",
      "saveOkLate",
      "saveError",
      "compileError",
      "compileFixed",
      "exportOk",
      "exportError",
      "agentSlow",
      "agentError",
      "focusExit",
      "feed",
      "play",
      "poseCycle",
      "poseCycleBlocked",
      "menuPeekUnder",
      "menuPerchSide",
    ] as const;
    for (const key of keys) {
      for (const line of petLinePool(key))
        expect(line.length, line).toBeLessThanOrEqual(22);
    }
    for (const line of petLinePool("compileErrorLine")) {
      const filled = line.replace("{line}", "999");
      expect(filled.length, filled).toBeLessThanOrEqual(22);
    }
  });

  it("picks deterministically from r", () => {
    expect(petLine("click", {}, 0)).toBe(petLinePool("click")[0]);
    expect(petLine("click", {}, 0.999)).toBe(petLinePool("click")[petLinePool("click").length - 1]);
  });

  it("keeps a large writing-tip chatter pool and 100+ lines overall", () => {
    expect(petLinePool("chatter").length).toBeGreaterThanOrEqual(80);
    expect(petLineTotal()).toBeGreaterThanOrEqual(100);
  });
});
