/**
 * 分片扫描默认参数的**防漂移守卫**。
 *
 * 为什么需要：这两个数字（窗口大小 / 重叠）决定了"跨章矛盾能不能被同一窗看到"，
 * 而它们存在于**两处**——后端路由的默认值与前端请求里的兜底值。只改一处的话：
 * 界面点「全书一致性扫描」时用的还是旧参数，而代码看起来已经改好了。
 * （本次就是这么踩到的：后端默认值先改成 12/4，前端仍写着 `?? 6 / ?? 2`。）
 *
 * 判据直接读后端源码，所以后端改数字而前端没跟上时这里会红——和 timeouts.test.ts
 * 读 llm_budget.py 是同一套做法。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { CONSISTENCY_SCAN_DEFAULTS } from "./projects";

const BACKEND_SCAN = fileURLToPath(
  new URL("../../../backend/app/core/consistency_scan.py", import.meta.url)
);

/**
 * 从后端**唯一真源** `core/consistency_scan.py` 里取出默认窗口参数。
 *
 * 注意不要改去解析 HTTP 路由的签名：路由现在写的是常量名（`size: int = DEFAULT_WINDOW_SIZE`），
 * 而常量的值在那边——真源只有一个，这个测试也只该读一个文件。
 */
function backendDefaults(): { size: number; overlap: number } {
  const src = readFileSync(BACKEND_SCAN, "utf8");
  const size = /^DEFAULT_WINDOW_SIZE\s*=\s*(\d+)/m.exec(src);
  const overlap = /^DEFAULT_WINDOW_OVERLAP\s*=\s*(\d+)/m.exec(src);
  expect(size, "后端里找不到 DEFAULT_WINDOW_SIZE").not.toBeNull();
  expect(overlap, "后端里找不到 DEFAULT_WINDOW_OVERLAP").not.toBeNull();
  return { size: Number(size![1]), overlap: Number(overlap![1]) };
}

describe("分片扫描默认参数（前后端必须一致）", () => {
  it("前端兜底值与后端路由默认值相同", () => {
    expect(CONSISTENCY_SCAN_DEFAULTS).toEqual(backendDefaults());
  });

  it("同窗距离上限靠 overlap 保证：至少覆盖「隔两章」的线索", () => {
    // 可推导的规律：相距 ≤ overlap 章的章对必然同窗（见 backend/tests/test_scan_exposure.py）
    expect(CONSISTENCY_SCAN_DEFAULTS.overlap).toBeGreaterThanOrEqual(2);
  });

  it("窗口不能小于重叠（否则步长会退化成 0 或负数）", () => {
    expect(CONSISTENCY_SCAN_DEFAULTS.size).toBeGreaterThan(CONSISTENCY_SCAN_DEFAULTS.overlap);
  });

  it("窗口别大到让单次调用吃进整本书", () => {
    // 上界不是硬标准，但 20 章以上的窗口会把"长上下文失效"的问题搬到窗口内部
    expect(CONSISTENCY_SCAN_DEFAULTS.size).toBeLessThanOrEqual(20);
  });
});
