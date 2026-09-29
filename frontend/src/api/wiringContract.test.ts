import { describe, expect, it } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

/**
 * 接线守卫：**后端做完了、前端没人传参**这一类的通用闸门。
 *
 * 为什么需要它（这不是假设，是本项目真实发生过三次的事故）
 * --------------------------------------------------------
 * 1. 设置页送的键名是 `base_url`，而后端 Pydantic 模型声明的是 `api_base_url`。
 *    未知字段被默认忽略 → 接口返回 200、界面提示"已保存到账号"、数据库那列一直是
 *    默认值。后果不只是显示难看：请求时用「用户自己的 Key + 那个默认地址」发出去，
 *    **用户的 Key 被送到了他没有指定的域名**。
 * 2. 导出器支持 `adaptive_reader` 开关，而**两个导出端点都没传它**——功能做完了，
 *    没有任何入口（`lib/storyReport.ts` 甚至只好叫作者手工往 .rpy 里加）。
 * 3. 协作实时推送从 `localStorage` 取 token，而 token 早已只存在内存里 →
 *    事件流永远 401，3 天里打了 31,958 次 401，章节锁/批注/在线状态全部不来。
 *
 * 三次都是同一个形状：**能力在后端齐了，前端少传一个参数或少接一根线**，
 * 而所有单测、类型检查、构建都是绿的——因为它们各自只看自己那一半。
 *
 * 本项目的既有做法是"用守卫测试把两半钉在一起"——注意它们分散在**两侧**：
 * `backend/tests/test_settings_put_contract.py`（解析 TS 里 `putSettings({...})` 的
 * 顶层键，断言它们都是后端 schema 的字段）、`scanDefaults.test.ts`（读后端源码保证
 * 两处默认值不分叉）、`timeouts.test.ts`（读后端常量保证前端阶梯不更紧）、
 * `fieldLimits.test.ts`。这个文件把那几处的思路**收敛成一张可扩展的注册表**：
 * 以后新加一个产品开关，只要往 `WIRINGS` 里加一行。
 *
 * 怎么加一条
 * ----------
 * 往 `WIRINGS` 里加 `{ name, backend, frontend }`：
 * - `backend`：后端那个开关的**特征字符串**（参数名 / 查询串 / 字段名）。
 *   要求它在指定的后端文件里出现——证明后端确实有这个能力。
 * - `frontend`：前端必须出现的一处调用特征（正则）。
 * 两条都对上才算接线完成；任一条对不上就红，并在消息里说清"缺的是哪一半"。
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND_SRC = resolve(HERE, "..");
const REPO_ROOT = resolve(FRONTEND_SRC, "..", "..");

function readRepoFile(relPath: string): string {
  const abs = resolve(REPO_ROOT, relPath);
  if (!existsSync(abs)) {
    // 读不到源码时**报错而不是跳过**：这个仓库明确区分"守护通过"与"没读到"，
    // 跳过会让守卫在最需要它的时候（文件被挪走）静默失效。
    throw new Error(`接线守卫读不到源码：${relPath}（期望在 ${abs}）`);
  }
  return readFileSync(abs, "utf8");
}

function readFrontendSources(relPaths: string[]): string {
  return relPaths.map(readRepoFile).join("\n");
}

type Wiring = {
  /** 人话名字，红了的时候要能一眼看懂缺的是什么 */
  name: string;
  /** 后端证据：必须在 `backend.file` 里出现 */
  backend: { file: string; needle: string };
  /** 前端证据：必须在 `frontend.files` 的全部内容里命中 */
  frontend: { files: string[]; pattern: RegExp };
};

const WIRINGS: Wiring[] = [
  {
    name: "导出开关 adaptive_reader（单文件 .rpy）",
    backend: { file: "backend/app/api/v1/projects.py", needle: "adaptive_reader" },
    frontend: {
      files: ["frontend/src/api/projects.ts"],
      // 必须钉到**真正在建 URL 的那一行**（`/export/rpy${query}`），而不是
      // 泛泛地找 `adaptive_reader=true`：后者在 `validateRpy` 里也存在，
      // 于是「exportRpy 根本没传这个参数」的原始缺陷会被漏掉——实测过，
      // 第一版就是这样写的，它对着修复前的代码也是绿的（假绿）。
      pattern: /export\/rpy\$\{query\}/,
    },
  },
  {
    name: "导出开关 adaptive_reader（整包 zip）",
    backend: { file: "backend/app/api/v1/projects.py", needle: "adaptive_reader" },
    frontend: {
      files: ["frontend/src/api/projects.ts"],
      pattern: /export\/bundle\$\{query\}/,
    },
  },
  {
    name: "导出体检端点 /export/rpy/validate",
    backend: { file: "backend/app/api/v1/projects.py", needle: "/export/rpy/validate" },
    frontend: {
      files: ["frontend/src/api/projects.ts"],
      pattern: /export\/rpy\/validate/,
    },
  },
  {
    name: "设置写入契约 api_base_url（键名曾被静默丢弃）",
    backend: { file: "backend/app/schemas/__init__.py", needle: "api_base_url" },
    frontend: {
      // 键名必须出现在**真正提交的那处**（SettingsModal 的 putSettings 调用），
      // 只出现在类型定义里不算接上——事故正是"类型对、送出的键名错"。
      files: ["frontend/src/components/SettingsModal.tsx"],
      pattern: /api_base_url:\s*next\.baseUrl/,
    },
  },
  {
    name: "跨章一致性扫描 consistency-scan",
    backend: { file: "backend/app/api/v1/projects.py", needle: "analysis/consistency-scan" },
    frontend: {
      files: ["frontend/src/api/projects.ts"],
      pattern: /analysis\/consistency-scan/,
    },
  },
  {
    // 组件层的**最薄接线测试**。审计的结论是"React 层 0 单测，而上面那三起事故
    // 全都发生在组件层"，所以这里不铺渲染测试，只针对最容易断的那根线做源码级断言。
    name: "AI 责编聊天必须走流式端点",
    backend: { file: "backend/app/api/v1/projects.py", needle: "/agent/stream" },
    frontend: {
      files: ["frontend/src/components/AgentChat.tsx"],
      // 钉"组件里真的调了流式那个函数"：改回非流式不会有类型错误，
      // 但用户会在长回答上盯着空白页等（并且流式与同步两档的超时预算不一样）。
      pattern: /await runAgentStream\(/,
    },
  },
  {
    // 写入闸门的**两半**：聊天只拿方案（apply_actions:false），确认那一半必须真的接上
    // /agent/apply-actions。只做前一半就成了"永远不写"，只做后一半则等于没有闸——
    // 这两种断法在类型上都看不出来，所以两半各钉一条。
    name: "写入闸门：聊天阶段只拿方案、不落库",
    backend: { file: "backend/app/api/v1/projects.py", needle: "apply_actions" },
    frontend: {
      files: ["frontend/src/components/AgentChat.tsx"],
      pattern: /apply_actions:\s*false/,
    },
  },
  {
    name: "写入闸门：确认后才调 /agent/apply-actions",
    backend: { file: "backend/app/api/v1/projects.py", needle: "/agent/apply-actions" },
    frontend: {
      files: ["frontend/src/components/AgentChat.tsx"],
      pattern: /await applyAgentActions\(/,
    },
  },
];

describe("接线守卫：后端有的开关，前端必须真的接上", () => {
  it("注册表本身不能是空的（否则这个文件永远绿）", () => {
    expect(WIRINGS.length).toBeGreaterThanOrEqual(4);
    for (const w of WIRINGS) {
      expect(w.name.length).toBeGreaterThan(4);
      expect(w.backend.file).toMatch(/^backend\//);
      for (const f of w.frontend.files) {
        expect(f).toMatch(/^frontend\//);
      }
    }
  });

  for (const wiring of WIRINGS) {
    it(`${wiring.name}：后端有、前端也接上了`, () => {
      const backendSrc = readRepoFile(wiring.backend.file);
      expect(
        backendSrc.includes(wiring.backend.needle),
        `后端那一半不在了：${wiring.backend.file} 里找不到 ${wiring.backend.needle}。` +
          `要么它被改名/删除，要么这条接线已经作废——两种情况都要人来显式决定。`
      ).toBe(true);

      const frontendSrc = readFrontendSources(wiring.frontend.files);
      expect(
        wiring.frontend.pattern.test(frontendSrc),
        `前端那一半没接上：${wiring.frontend.files.join(", ")} 里没有命中 ` +
          `${wiring.frontend.pattern}。这正是本项目反复出现的那类缺陷——` +
          `后端能力齐了、前端少传一个参数，而类型检查、单测、构建全是绿的。`
      ).toBe(true);
    });
  }
});

describe("接线守卫的机制本身要可靠", () => {
  it("读不到文件时必须抛错，不能当成通过", () => {
    expect(() => readRepoFile("backend/app/__nonexistent_for_guard__.py")).toThrow(
      /接线守卫读不到源码/
    );
  });

  it("真的能发现'前端少了那一半'（用一个必然不命中的模式自证）", () => {
    const src = readFrontendSources(["frontend/src/api/projects.ts"]);
    expect(/__no_such_thing_in_this_codebase__/.test(src)).toBe(false);
  });
});
