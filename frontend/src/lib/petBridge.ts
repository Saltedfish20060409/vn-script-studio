import type { PetAppEvent } from "./petMachine";

/** 工作台里的编译、导出、搭档，把结果送到桌宠。组件台也能用同一条通道截图。 */
export type PetSignal =
  | { kind: "app"; event: PetAppEvent; line?: number }
  | { kind: "sleep" };

type Listener = (signal: PetSignal) => void;

const listeners = new Set<Listener>();

export function emitPetApp(event: PetAppEvent, line?: number): void {
  const signal: PetSignal = { kind: "app", event, line };
  for (const listener of listeners) listener(signal);
}

export function emitPetSleep(): void {
  const signal: PetSignal = { kind: "sleep" };
  for (const listener of listeners) listener(signal);
}

export function subscribePet(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
