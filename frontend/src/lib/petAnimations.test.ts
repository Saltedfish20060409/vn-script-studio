import { describe, expect, it } from "vitest";
import {
  PET_ANIMATIONS,
  PET_CANVAS,
  petFrameUrl,
  type PetActionId,
} from "./petAnimations";

const DOC_P0: Record<string, { frames: number; loop: boolean }> = {
  breath_idle: { frames: 4, loop: true },
  blink: { frames: 3, loop: false },
  walk_side_r: { frames: 6, loop: true },
  perch_top: { frames: 2, loop: true },
  peek_over: { frames: 4, loop: false },
  peek_side_r: { frames: 4, loop: false },
};

const DOC_P1: Record<string, { frames: number; loop: boolean }> = {
  perch_side_r: { frames: 2, loop: true },
  peek_under: { frames: 4, loop: false },
  hide_corner: { frames: 1, loop: false },
  slip_r: { frames: 4, loop: false },
  react_fluster: { frames: 4, loop: false },
  react_cheer: { frames: 4, loop: false },
};

describe("petAnimations (per docs/mascot-pet-art-brief.md)", () => {
  it("P0 frame counts and loop flags match the brief", () => {
    for (const [id, expected] of Object.entries(DOC_P0)) {
      const spec = PET_ANIMATIONS[id as PetActionId];
      expect(spec.frames, id).toBe(expected.frames);
      expect(spec.loop, id).toBe(expected.loop);
    }
  });

  it("P1 frame counts and loop flags match the brief", () => {
    for (const [id, expected] of Object.entries(DOC_P1)) {
      const spec = PET_ANIMATIONS[id as PetActionId];
      expect(spec.frames, id).toBe(expected.frames);
      expect(spec.loop, id).toBe(expected.loop);
    }
  });

  it("hold durations match the brief timing", () => {
    expect(PET_ANIMATIONS.breath_idle.holdMs).toEqual([400, 400, 400, 400]);
    expect(PET_ANIMATIONS.blink.holdMs).toEqual([60, 80, 60]);
    expect(PET_ANIMATIONS.walk_side_r.holdMs).toEqual(
      Array(6).fill(120)
    );
    expect(PET_ANIMATIONS.perch_top.holdMs).toEqual([1000, 1000]);
    expect(PET_ANIMATIONS.react_fluster.holdMs).toEqual([80, 140, 160, 160]);
  });

  it("every spec has matching hold duration count", () => {
    for (const spec of Object.values(PET_ANIMATIONS)) {
      expect(spec.holdMs.length, spec.id).toBe(spec.frames);
    }
  });

  it("peek actions stop at frame 03 and use B canvas", () => {
    expect(PET_ANIMATIONS.peek_over.stopAt).toBe(3);
    expect(PET_ANIMATIONS.peek_over.canvas).toBe("B");
    expect(PET_ANIMATIONS.peek_side_r.stopAt).toBe(3);
  });

  it("frame URLs follow pet/{A_body|B_peek}/pet_{base}{_r}_{nn}.png", () => {
    const walk = PET_ANIMATIONS.walk_side_r;
    expect(petFrameUrl(walk, 0)).toBe("/pet/A_body/pet_walk_side_r_01.png");
    expect(petFrameUrl(walk, 5)).toBe("/pet/A_body/pet_walk_side_r_06.png");
    const peek = PET_ANIMATIONS.peek_over;
    expect(petFrameUrl(peek, 2)).toBe("/pet/B_peek/pet_peek_over_03.png");
  });

  it("canvas sizes follow the brief", () => {
    expect(PET_CANVAS.A).toEqual({ w: 512, h: 768 });
    expect(PET_CANVAS.B).toEqual({ w: 384, h: 384 });
  });

  it("foot anchor is at horizontal center, 48px above the bottom (A)", () => {
    expect(PET_ANIMATIONS.breath_idle.anchor?.foot).toEqual({
      x: 256,
      y: 768 - 48,
    });
  });
});
