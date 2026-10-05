import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { buildFixture } from "../../scripts/gen_writing_local_cases";

/**
 * 跨端夹具守卫：`shared/test-fixtures/writing_local_cases.json` 必须等于当前 Web 实现现算的结果。
 *
 * Android 端（`feature/editor` 的 `WritingLocalCasesTest`）对同一份文件断言它的 Kotlin 移植版。
 * 所以：改了 `editorAssist.ts` / `typoRules.ts` / `wordCount.ts` 的行为 → 这里变红 →
 * 在 frontend 目录运行 `npx tsx scripts/gen_writing_local_cases.ts` 重新生成 → Android 测试随之变红，
 * 提醒同步移植。两端不可能悄悄分叉。
 */
describe("writing_local_cases 夹具", () => {
  it("与当前实现的输出一致（改了规则请重新生成夹具）", () => {
    const path = resolve(__dirname, "../../../shared/test-fixtures/writing_local_cases.json");
    const onDisk = JSON.parse(readFileSync(path, "utf-8"));
    // 经 JSON 往返，抹平 undefined 字段，与写盘时一致
    const fresh = JSON.parse(JSON.stringify(buildFixture()));
    expect(fresh).toEqual(onDisk);
  });
});
