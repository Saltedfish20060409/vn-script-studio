import { describe, expect, it } from "vitest";
import type { PetBodyAsset, PetManifest } from "./petManifest";
import { createPetState, type PetState } from "./petMachine";
import {
  anchorOf,
  bodyMetrics,
  boxAt,
  canPeekAt,
  canPerchAt,
  classifyDrop,
  emoteBox,
  mirroredAnchor,
  petScale,
  petVisual,
  upsideDownAnchor,
  PET_EMOTE_MIN_PX,
  FRAME_EDGE_BAND_PX,
  PEEK_DEPTH_PX,
  SIDE_BAND_PX,
} from "./petVisual";

const emote = { size: 42, above_right: [251, 7], zzz: [265, 1], temple: [268, 52] } as const;

function body(canvas: "A" | "B", type: PetBodyAsset["anchor"]["type"], x: number, y: number): PetBodyAsset {
  return {
    canvas,
    src: "x.webp",
    anchor: { type, x, y },
    emote: { size: emote.size, above_right: [...emote.above_right], zzz: [...emote.zzz], temple: [...emote.temple] },
  };
}

const M: PetManifest = {
  version: 1,
  canvas: { A: { w: 320, h: 480 }, B: { w: 240, h: 240 } },
  bodies: {
    idle: body("A", "foot", 160, 450),
    perch_top: body("A", "sit", 160, 316.67),
    peek_over: body("B", "bottom", 120, 240),
    peek_side_r: body("B", "grip", 234.06, 149.97),
    peek_side_l: body("B", "grip", 5.62, 149.69),
    hide_corner: body("A", "foot", 160, 450),
    sleep: body("A", "foot", 160, 450),
    headpat: body("A", "foot", 160, 450),
    held: body("A", "grab", 160.83, 20),
    happy_jump: body("A", "foot", 160, 450),
    happy_land: body("A", "foot", 160, 450),
    perch_side: body("A", "side", 37.5, 450),
  },
  walk: {
    r: { src: "w.webp", frames: [[0, 0, 320, 480]], ms: 320, anchor: { type: "foot", x: 160, y: 450 }, emote: body("A", "foot", 0, 0).emote },
    l: { src: "w.webp", frames: [[0, 0, 320, 480]], ms: 320, anchor: { type: "foot", x: 160, y: 450 }, emote: body("A", "foot", 0, 0).emote },
  },
  feed: {
    src: "feed.webp",
    frames: [[0, 0, 320, 480]],
    ms: 380,
    anchor: { type: "foot", x: 160, y: 450 },
    emote: body("A", "foot", 0, 0).emote,
  },
  play: {
    src: "play.webp",
    frames: [[0, 0, 320, 480]],
    ms: 400,
    anchor: { type: "foot", x: 160, y: 450 },
    emote: body("A", "foot", 0, 0).emote,
  },
  faces: {},
};

const T0 = 1_000_000;
function st(patch: Partial<PetState>): PetState {
  return { ...createPetState(T0), ...patch };
}

describe("petVisual", () => {
  it("idle shows the standing body with blink and talk", () => {
    const v = petVisual(st({}));
    expect(v.body).toBe("idle");
    expect(v.face).toBe("idle");
    expect(v.canBlink).toBe(true);
    expect(v.canTalk).toBe(true);
  });

  it("expressions win over blink and mouth", () => {
    const v = petVisual(st({ body: "nod", mood: "happy" }));
    expect(v.body).toBe("idle");
    expect(v.expression).toBe("happy");
    expect(v.canBlink).toBe(false);
    expect(v.canTalk).toBe(false);
  });

  it("reactions keep the placed pose on the frame and only change the face", () => {
    const perched = petVisual(st({ placement: "perchTop", body: "nod", mood: "happy", emote: "heart" }));
    expect(perched.body).toBe("perch_top");
    expect(perched.expression).toBeNull();
    expect(perched.canBlink).toBe(true);
    const peek = petVisual(st({ placement: "peekOver", body: "fluster", mood: "fluster" }));
    expect(peek.body).toBe("peek_over");
    expect(peek.expression).toBe("fluster");
  });

  it("edges pick the side matching the screen edge", () => {
    expect(petVisual(st({ placement: "edgeLeft", body: "peekSide" })).body).toBe("peek_side_l");
    expect(petVisual(st({ placement: "edgeRight", body: "peekSide" })).body).toBe("peek_side_r");
  });

  it("peek under turns the peek sprite upside down, and the frame sides mirror only on the left", () => {
    const under = petVisual(st({ placement: "peekUnder", body: "peekOver" }));
    expect(under.body).toBe("peek_over");
    expect(under.face).toBe("peek_over");
    expect(under.upsideDown).toBe(true);
    const left = petVisual(st({ placement: "perchSideLeft" }));
    const right = petVisual(st({ placement: "perchSideRight" }));
    expect(left.body).toBe("perch_side");
    expect(left.mirror).toBe(true);
    expect(right.mirror).toBe(false);
    expect(right.upsideDown).toBe(false);
  });

  it("sleep closes the eyes on framed poses and uses the sitting sleep pose on the ground", () => {
    const ground = petVisual(st({ body: "sleep", emote: "zzz" }));
    expect(ground.body).toBe("sleep");
    expect(ground.face).toBeNull();
    expect(ground.emoteAnchor).toBe("zzz");
    const perched = petVisual(st({ placement: "perchTop", body: "sleep", emote: "zzz" }));
    expect(perched.body).toBe("perch_top");
    expect(perched.eyesClosed).toBe(true);
    expect(perched.canBlink).toBe(false);
  });

  it("menu feed/play use sequence bodies without face overlays", () => {
    const feed = petVisual(
      st({
        body: "feed",
        mood: "happy",
        emote: "heart",
        reaction: { priority: 2, until: T0 + 1520 },
      })
    );
    expect(feed.body).toBe("feed");
    expect(feed.face).toBeNull();
    expect(feed.canTalk).toBe(false);
    // 贴框时也不能盖掉喂食图集
    const onFrame = petVisual(
      st({
        placement: "perchTop",
        body: "feed",
        mood: "happy",
        emote: "heart",
      })
    );
    expect(onFrame.body).toBe("feed");
    const play = petVisual(
      st({
        body: "play",
        mood: "happy",
        emote: "dots",
        reaction: { priority: 2, until: T0 + 1600 },
      })
    );
    expect(play.body).toBe("play");
    expect(play.walkBob).toBe(false);
    expect(play.face).toBeNull();
    const wander = petVisual(st({ body: "walk" }));
    expect(wander.walkBob).toBe(true);
  });

  it("drag and walk override the placed pose", () => {
    expect(petVisual(st({ placement: "perchTop", body: "held" })).body).toBe("held");
    expect(petVisual(st({ placement: "dock", body: "walk" })).body).toBe("walk");
    expect(petVisual(st({ placement: "dock", body: "walk" })).face).toBeNull();
  });

  it("sweat hangs at the temple, other emotes above the head", () => {
    expect(petVisual(st({ emote: "sweat" })).emoteAnchor).toBe("temple");
    expect(petVisual(st({ emote: "question" })).emoteAnchor).toBe("above_right");
  });
});

describe("pet layout", () => {
  const s = petScale(128);

  it("A and B share one scale so heads match", () => {
    expect(s).toBeCloseTo(0.4);
  });

  it("boxAt / anchorOf round-trip", () => {
    const met = bodyMetrics(M, "perch_top");
    const b = boxAt(met, s, 500, 300);
    expect(anchorOf(met, s, b)).toEqual({ x: 500, y: 300 });
  });

  it("perch needs room for the hanging feet and the head", () => {
    const vp = { w: 1400, h: 900, bottomReserve: 50 };
    expect(canPerchAt(M, s, 400, vp)).toBe(true);
    expect(canPerchAt(M, s, 800, vp)).toBe(false);
    expect(canPerchAt(M, s, 40, vp)).toBe(false);
  });

  it("peek needs the head on screen", () => {
    expect(canPeekAt(M, s, 300)).toBe(true);
    expect(canPeekAt(M, s, 20)).toBe(false);
  });

  it("emote never renders below the readable minimum", () => {
    const met = bodyMetrics(M, "idle");
    expect(emoteBox(met, "above_right", s).size * s).toBeGreaterThanOrEqual(PET_EMOTE_MIN_PX - 1e-9);
    expect(emoteBox(met, "above_right", 1).size).toBe(42);
  });

  it("turning the peek anchor puts the old bottom on the top edge", () => {
    const met = bodyMetrics(M, "peek_over");
    const turned = upsideDownAnchor(met);
    expect(turned.anchor).toEqual({ type: "bottom", x: 120, y: 0 });
    const side = bodyMetrics(M, "perch_side");
    expect(mirroredAnchor(side).anchor.x).toBeCloseTo(side.w - side.anchor.x);
  });
});

describe("classifyDrop", () => {
  const frame = { left: 200, right: 600, top: 180, bottom: 520 };
  const w = 1200;

  it("sits on the top edge, peeks over just below it, and hangs under the bottom edge", () => {
    expect(classifyDrop({ x: 400, y: frame.top }, 400, frame, w)).toBe("perchTop");
    expect(classifyDrop({ x: 400, y: frame.top + FRAME_EDGE_BAND_PX + 10 }, 400, frame, w)).toBe("peekOver");
    expect(classifyDrop({ x: 400, y: frame.top + PEEK_DEPTH_PX + 20 }, 400, frame, w)).toBe("free");
    expect(classifyDrop({ x: 400, y: frame.bottom }, 400, frame, w)).toBe("peekUnder");
  });

  it("leans on the outer vertical edges and still treats the screen edge as the screen edge", () => {
    expect(classifyDrop({ x: frame.left - SIDE_BAND_PX + 4, y: 300 }, 400, frame, w)).toBe("perchSideLeft");
    expect(classifyDrop({ x: frame.right + 20, y: 300 }, 400, frame, w)).toBe("perchSideRight");
    expect(classifyDrop({ x: frame.left - SIDE_BAND_PX - 8, y: 300 }, 400, frame, w)).toBe("free");
    expect(classifyDrop({ x: 4, y: frame.top }, 4, frame, w)).toBe("edgeLeft");
    expect(classifyDrop({ x: w - 4, y: frame.bottom }, w - 4, frame, w)).toBe("edgeRight");
  });
});
