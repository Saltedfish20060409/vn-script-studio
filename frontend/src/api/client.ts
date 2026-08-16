/**
 * Unified API client entry point.
 *
 * The former monolith was split into domain modules (http/auth/projects/
 * pipeline/voice/lore/misc) under ./; everything is re-exported here so
 * existing `import { ... } from "../api/client"` call sites keep working
 * unchanged.
 */
export * from "./http";
export * from "./auth";
export * from "./projects";
export * from "./pipeline";
export * from "./voice";
export * from "./lore";
export * from "./misc";
