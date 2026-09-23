import { beforeEach, describe, expect, it } from "vitest";
import {
  buildPlaytestRecord,
  createClientRunId,
  enqueuePlaytest,
  flushPlaytestQueue,
  isPlaytestTelemetryDisabled,
  isTelemetryDisabled,
  queuedPlaytestCount,
  resetPlaytestTelemetry,
  sanitizeIdentifier,
  setPlaytestSender,
  startPlaytestSession,
  MAX_CHOICES_PER_RUN,
  type PlaytestRecordIn,
  type PlaytestSendOutcome,
} from "./playtestTelemetry";

/** 固定"现在"，让时间窗口校验可复现。 */
const NOW = Date.UTC(2026, 0, 2, 0, 0, 0);
const RUN_ID = "abcdefgh";

function payloadOf(clientRunId = RUN_ID): PlaytestRecordIn {
  return buildPlaytestRecord(
    { clientRunId, startedAt: "2026-01-01T00:00:00.000Z" },
    { now: NOW }
  ).payload;
}

/** 立刻结算的假传输：记录收到的上报体，并按需返回指定的结果。 */
function collectingSender(outcome: PlaytestSendOutcome = "ok") {
  const calls: Array<{ projectId: string; payload: PlaytestRecordIn; keepalive: boolean }> = [];
  const send = (
    projectId: string,
    payload: PlaytestRecordIn,
    opts: { keepalive: boolean }
  ): Promise<PlaytestSendOutcome> => {
    calls.push({ projectId, payload, keepalive: opts.keepalive });
    return Promise.resolve(outcome);
  };
  return { calls, send };
}

/** 等 flush 的 promise 链跑完（session.finish 内部是 fire-and-forget）。 */
function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(() => {
  resetPlaytestTelemetry();
});

describe("client_run_id 的熵与字符集", () => {
  it("优先用 crypto.randomUUID()", () => {
    const id = createClientRunId({
      randomUUID: () => "11111111-2222-3333-4444-555555555555",
    });
    expect(id).toBe("11111111-2222-3333-4444-555555555555");
  });

  it("randomUUID 返回的不是 URL 安全串时退化到 getRandomValues", () => {
    const id = createClientRunId({
      randomUUID: () => "not url safe!",
      getRandomValues: (bytes) => {
        bytes.fill(0);
        return bytes;
      },
    });
    expect(id).toBe("AAAAAAAAAAAAAAAA");
    expect(id).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
  });

  it("randomUUID 抛异常也不炸：退化到 getRandomValues", () => {
    const id = createClientRunId({
      randomUUID: () => {
        throw new Error("insecure context");
      },
      getRandomValues: (bytes) => {
        bytes.fill(63);
        return bytes;
      },
    });
    expect(id).toBe("________________");
  });

  it("没有随机源时返回空串（绝不退回 Math.random 兜底）", () => {
    expect(createClientRunId(null)).toBe("");
    expect(createClientRunId({})).toBe("");
  });

  it("真实随机源：200 个 id 全部命中后端的 8~64 位 URL 安全字符集且互不相同", () => {
    const ids = new Set<string>();
    for (let i = 0; i < 200; i++) ids.add(createClientRunId());
    expect(ids.size).toBe(200);
    for (const id of ids) {
      expect(id).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
      expect(id.length).toBeGreaterThanOrEqual(8);
      expect(id.length).toBeLessThanOrEqual(64);
    }
  });
});

describe("标识符净化（前端也先丢一遍）", () => {
  it("ASCII 标识符原样通过（首尾空格去掉）", () => {
    expect(sanitizeIdentifier("  ending_good  ")).toBe("ending_good");
    expect(sanitizeIdentifier("menu:1.a-b_c")).toBe("menu:1.a-b_c");
  });

  it("中文 / 空格 / 标点开头 / 数字开头一律清空", () => {
    expect(sanitizeIdentifier("第一章")).toBe("");
    expect(sanitizeIdentifier("ending good")).toBe("");
    expect(sanitizeIdentifier("1ending")).toBe("");
    expect(sanitizeIdentifier("「你好」")).toBe("");
  });

  it("非字符串与超长值清空", () => {
    expect(sanitizeIdentifier(undefined)).toBe("");
    expect(sanitizeIdentifier(42)).toBe("");
    expect(sanitizeIdentifier("a".repeat(65))).toBe("");
    expect(sanitizeIdentifier("a".repeat(64))).toBe("a".repeat(64));
  });
});

describe("上报体构造", () => {
  it("按后端白名单输出 snake_case 字段，seq 按顺序补 0 起", () => {
    const record = buildPlaytestRecord(
      {
        clientRunId: RUN_ID,
        startedAt: "2026-01-01T00:00:00.000Z",
        endedAt: "2026-01-01T00:10:00.000Z",
        chapterCount: 2,
        endingLabel: "ending_good",
        choices: [
          {
            chapterId: "ch1",
            label: "start",
            menuId: "menu_1",
            choiceIndex: 0,
            condition: "affection > 5",
            conditionPassed: true,
          },
          {
            chapterId: "ch1",
            label: "start",
            menuId: "menu_1",
            choiceIndex: 1,
            condition: "",
            conditionPassed: false,
          },
        ],
      },
      { now: NOW }
    );

    expect(record.clientRunId).toBe(RUN_ID);
    expect(record.choiceCount).toBe(2);
    expect(record.payload).toEqual({
      run: {
        client_run_id: RUN_ID,
        started_at: "2026-01-01T00:00:00.000Z",
        ended_at: "2026-01-01T00:10:00.000Z",
        chapter_count: 2,
        choice_count: 2,
        ending_label: "ending_good",
      },
      choices: [
        {
          seq: 0,
          chapter_id: "ch1",
          label: "start",
          menu_id: "menu_1",
          choice_index: 0,
          condition_passed: true,
        },
        {
          seq: 1,
          chapter_id: "ch1",
          label: "start",
          menu_id: "menu_1",
          choice_index: 1,
          condition_passed: false,
        },
      ],
    });
  });

  it("空选择历史也能构造出合法 run（一次没选的试玩同样是一次样本）", () => {
    const record = buildPlaytestRecord(
      { clientRunId: RUN_ID, startedAt: NOW, chapterCount: 1 },
      { now: NOW }
    );
    expect(record.payload.choices).toEqual([]);
    expect(record.choiceCount).toBe(0);
    expect(record.payload.run.choice_count).toBe(0);
    expect(record.payload.run.client_run_id).toBe(RUN_ID);
    expect(record.payload.run.ended_at).toBe("");
  });

  it("choices 传 null / undefined 不抛异常", () => {
    expect(
      buildPlaytestRecord({ clientRunId: RUN_ID, choices: null }, { now: NOW }).payload.choices
    ).toEqual([]);
    expect(
      buildPlaytestRecord({ clientRunId: RUN_ID, choices: undefined }, { now: NOW }).payload
        .choices
    ).toEqual([]);
  });

  it("中文 menuId / chapterId / label 被前端清空并计数（不指望后端兜底）", () => {
    const record = buildPlaytestRecord(
      {
        clientRunId: RUN_ID,
        chapterCount: 1,
        choices: [
          {
            chapterId: "第一章",
            label: "温柔路线",
            menuId: "menu_1",
            choiceIndex: 2,
            conditionPassed: true,
          },
        ],
      },
      { now: NOW }
    );
    expect(record.payload.choices[0]).toEqual({
      seq: 0,
      chapter_id: "",
      label: "",
      menu_id: "menu_1",
      choice_index: 2,
      condition_passed: true,
    });
    expect(record.dropped.emptiedValues).toBe(2);
  });

  it("不在白名单里的字段（condition）在前端就丢掉并记名", () => {
    const record = buildPlaytestRecord(
      {
        clientRunId: RUN_ID,
        choices: [
          { menuId: "menu_1", condition: "affection > 5", conditionPassed: true },
        ],
      },
      { now: NOW }
    );
    expect(record.dropped.fieldNames).toEqual(["condition"]);
    expect(Object.keys(record.payload.choices[0])).not.toContain("condition");
  });

  it("seq 缺省用数组位置；重复 seq 保留最后一条并按 seq 升序", () => {
    const record = buildPlaytestRecord(
      {
        clientRunId: RUN_ID,
        choices: [
          { menuId: "menu_1", choiceIndex: 3, seq: 2 },
          { menuId: "menu_1", choiceIndex: 0 },
          { menuId: "menu_1", choiceIndex: 9, seq: 2 },
          { menuId: "menu_1", choiceIndex: 1 },
        ],
      },
      { now: NOW }
    );
    expect(record.payload.choices.map((c) => c.seq)).toEqual([1, 2, 3]);
    expect(record.payload.choices.map((c) => c.choice_index)).toEqual([0, 9, 1]);
  });

  it("seq 非法（负数 / 超上限 / 非整数）整条丢弃，并计入 rejectedChoices", () => {
    const record = buildPlaytestRecord(
      {
        clientRunId: RUN_ID,
        choices: [
          { menuId: "menu_1", seq: -1 },
          { menuId: "menu_1", seq: 1.5 },
          { menuId: "menu_1", seq: MAX_CHOICES_PER_RUN + 1 },
          { menuId: "menu_1", choiceIndex: 0 },
        ],
      },
      { now: NOW }
    );
    expect(record.dropped.rejectedChoices).toBe(3);
    expect(record.choiceCount).toBe(1);
    expect(record.payload.choices[0].seq).toBe(3);
  });

  it("null 元素被当成整条非法丢弃", () => {
    const record = buildPlaytestRecord(
      { clientRunId: RUN_ID, choices: [null, { menuId: "menu_1" }, undefined] },
      { now: NOW }
    );
    expect(record.dropped.rejectedChoices).toBe(2);
    expect(record.choiceCount).toBe(1);
  });

  it("超过单次上限的选择被截断并计数（与后端 2000 条上限对齐）", () => {
    const many = Array.from({ length: MAX_CHOICES_PER_RUN + 5 }, () => ({
      menuId: "menu_1",
      choiceIndex: 0,
    }));
    const record = buildPlaytestRecord(
      { clientRunId: RUN_ID, choices: many },
      { now: NOW }
    );
    expect(record.choiceCount).toBe(MAX_CHOICES_PER_RUN);
    expect(record.dropped.truncatedChoices).toBe(5);
  });

  it("chapter_count 越界被夹住，非数字归 0", () => {
    expect(
      buildPlaytestRecord({ clientRunId: RUN_ID, chapterCount: -3 }, { now: NOW }).payload.run
        .chapter_count
    ).toBe(0);
    expect(
      buildPlaytestRecord({ clientRunId: RUN_ID, chapterCount: 999999 }, { now: NOW }).payload
        .run.chapter_count
    ).toBe(5000);
    expect(
      buildPlaytestRecord(
        { clientRunId: RUN_ID, chapterCount: "2" as unknown as number },
        { now: NOW }
      ).payload.run.chapter_count
    ).toBe(0);
  });

  it("结束时间早于开始时间时不报结束时间（宁可不报，也不污染时长统计）", () => {
    const record = buildPlaytestRecord(
      {
        clientRunId: RUN_ID,
        startedAt: "2026-01-01T00:10:00.000Z",
        endedAt: "2026-01-01T00:00:00.000Z",
      },
      { now: NOW }
    );
    expect(record.payload.run.ended_at).toBe("");
  });

  it("离谱时间（1999 年 / 太未来）被抹成空串", () => {
    expect(
      buildPlaytestRecord(
        { clientRunId: RUN_ID, startedAt: "1999-12-31T23:59:00.000Z" },
        { now: NOW }
      ).payload.run.started_at
    ).toBe("");
    expect(
      buildPlaytestRecord({ clientRunId: RUN_ID, endedAt: NOW + 3 * 86400000 }, { now: NOW })
        .payload.run.ended_at
    ).toBe("");
  });

  it("clientRunId 缺失/非法时重新生成合法 id", () => {
    const generated = buildPlaytestRecord(
      { startedAt: NOW },
      { now: NOW, crypto: { getRandomValues: (b) => b.fill(0) } }
    );
    expect(generated.clientRunId).toBe("AAAAAAAAAAAAAAAA");
    const replaced = buildPlaytestRecord(
      { clientRunId: "短", startedAt: NOW },
      { now: NOW, crypto: { getRandomValues: (b) => b.fill(0) } }
    );
    expect(replaced.clientRunId).toBe("AAAAAAAAAAAAAAAA");
    expect(replaced.payload.run.client_run_id).toBe("AAAAAAAAAAAAAAAA");
  });

  it("没有随机源又没有给 id 时不编造 id（调用方据此放弃上报）", () => {
    const record = buildPlaytestRecord({ startedAt: NOW }, { now: NOW, crypto: null });
    expect(record.clientRunId).toBe("");
    expect(record.payload.run.client_run_id).toBe("");
  });
});

describe("403 telemetry_disabled 是「关闭」而不是「失败」", () => {
  it("403 + detail.code=telemetry_disabled → true", () => {
    expect(
      isTelemetryDisabled({
        status: 403,
        detail: { code: "telemetry_disabled", message: "该工程未开启读者行为采集" },
      })
    ).toBe(true);
  });

  it("403 + detail 字符串里带 code → true", () => {
    expect(
      isTelemetryDisabled({
        status: 403,
        detail: '{"code":"telemetry_disabled"}',
        message: "该工程未开启读者行为采集（默认关闭，需作者显式开启）",
      })
    ).toBe(true);
  });

  it("其它 403（例如不是工程成员）不算「关了」", () => {
    expect(isTelemetryDisabled({ status: 403, detail: { code: "forbidden" } })).toBe(false);
    expect(isTelemetryDisabled({ status: 403, detail: "无权访问" })).toBe(false);
  });

  it("非 403 与非对象输入一律 false", () => {
    expect(isTelemetryDisabled({ status: 400, detail: { code: "telemetry_disabled" } })).toBe(
      false
    );
    expect(isTelemetryDisabled({ status: 500 })).toBe(false);
    expect(isTelemetryDisabled(null)).toBe(false);
    expect(isTelemetryDisabled("403")).toBe(false);
  });
});

describe("本地队列与批量 flush", () => {
  it("入队计入队；同一 (projectId, clientRunId) 再入队只替换不叠加", () => {
    expect(enqueuePlaytest("p1", payloadOf())).toBe("added");
    expect(queuedPlaytestCount()).toBe(1);
    const richer = buildPlaytestRecord(
      {
        clientRunId: RUN_ID,
        startedAt: NOW,
        choices: [{ menuId: "menu_1", choiceIndex: 0 }],
      },
      { now: NOW }
    ).payload;
    expect(enqueuePlaytest("p1", richer)).toBe("merged");
    expect(queuedPlaytestCount()).toBe(1);
  });

  it("projectId 为空 / client_run_id 非法 → 拒收", () => {
    expect(enqueuePlaytest("", payloadOf())).toBe("rejected");
    const bad = payloadOf();
    bad.run.client_run_id = "短";
    expect(enqueuePlaytest("p1", bad)).toBe("rejected");
    expect(queuedPlaytestCount()).toBe(0);
  });

  it("队列有上限：超出时丢最旧的，保留刚发生的", async () => {
    for (let i = 0; i < 10; i++) {
      const id = `runid-${String(i).padStart(3, "0")}`;
      expect(enqueuePlaytest("p1", payloadOf(id))).toBe("added");
    }
    expect(queuedPlaytestCount()).toBe(8);
    const { calls, send } = collectingSender();
    await flushPlaytestQueue({ send });
    const kept = calls.map((c) => c.payload.run.client_run_id);
    expect(kept).toContain("runid-009");
    expect(kept).not.toContain("runid-000");
  });

  it("flush 一次性把队列发出去，并发完队列就空了", async () => {
    enqueuePlaytest("p1", payloadOf());
    const { calls, send } = collectingSender();
    const first = await flushPlaytestQueue({ send });
    expect(first).toEqual({ sent: 1, failed: 0, skipped: 0, disabled: false });
    expect(calls).toHaveLength(1);
    expect(calls[0].projectId).toBe("p1");
    expect(queuedPlaytestCount()).toBe(0);

    const second = await flushPlaytestQueue({ send });
    expect(second.sent).toBe(0);
    expect(calls).toHaveLength(1);
  });

  it("失败就丢弃、不重试（队列不会攒着失败项反复刷接口）", async () => {
    enqueuePlaytest("p1", payloadOf());
    const { calls, send } = collectingSender("error");
    const outcome = await flushPlaytestQueue({ send });
    expect(outcome).toEqual({ sent: 0, failed: 1, skipped: 0, disabled: false });
    expect(queuedPlaytestCount()).toBe(0);
    await flushPlaytestQueue({ send });
    expect(calls).toHaveLength(1);
  });

  it("send 同步抛异常也只算一次失败，不炸调用方", async () => {
    enqueuePlaytest("p1", payloadOf());
    const outcome = await flushPlaytestQueue({
      send: () => {
        throw new Error("boom");
      },
    });
    expect(outcome.failed).toBe(1);
  });

  it("keepalive 选项透传给传输层（页面隐藏时的兜底）", async () => {
    enqueuePlaytest("p1", payloadOf());
    const { calls, send } = collectingSender();
    await flushPlaytestQueue({ send, keepalive: true });
    expect(calls[0].keepalive).toBe(true);
  });

  it("返回 disabled 时：清空队列、标记本次会话停上报、后续入队直接拒收", async () => {
    enqueuePlaytest("p1", payloadOf("runid-aaa"));
    enqueuePlaytest("p1", payloadOf("runid-bbb"));
    const outcome = await flushPlaytestQueue({ send: collectingSender("disabled").send });
    expect(outcome.disabled).toBe(true);
    expect(outcome.skipped).toBe(2);
    expect(queuedPlaytestCount()).toBe(0);
    expect(isPlaytestTelemetryDisabled()).toBe(true);
    expect(enqueuePlaytest("p1", payloadOf("runid-ccc"))).toBe("rejected");
  });

  it("停上报之后 flush 不再发任何请求", async () => {
    enqueuePlaytest("p1", payloadOf("runid-aaa"));
    await flushPlaytestQueue({ send: collectingSender("disabled").send });
    expect(isPlaytestTelemetryDisabled()).toBe(true);

    const { calls, send } = collectingSender();
    expect(enqueuePlaytest("p1", payloadOf("runid-bbb"))).toBe("rejected");
    const outcome = await flushPlaytestQueue({ send });
    expect(calls).toHaveLength(0);
    expect(outcome).toEqual({ sent: 0, failed: 0, skipped: 0, disabled: true });
  });
});

describe("试玩会话（一次试玩一次上报）", () => {
  it("没有 projectId / 没有随机源时返回 null（宁可不记）", () => {
    expect(startPlaytestSession({ projectId: "" })).toBe(null);
    expect(startPlaytestSession({ projectId: "p1", crypto: null })).toBe(null);
  });

  it("选择按顺序自动编号，finish 只上报一次", async () => {
    const { calls, send } = collectingSender();
    setPlaytestSender(send);
    const session = startPlaytestSession({
      projectId: "p1",
      chapterId: "ch1",
      startedAt: NOW,
      crypto: { getRandomValues: (b) => b.fill(1) },
    });
    expect(session).not.toBe(null);
    session?.addChoice({ chapterId: "ch1", menuId: "menu_1", choiceIndex: 0 });
    session?.addChoice({ chapterId: "ch1", menuId: "menu_1", choiceIndex: 2 });
    session?.finish({ endedAt: NOW + 60000, endingLabel: "ending_good" });
    await settle();

    expect(calls).toHaveLength(1);
    expect(calls[0].payload.run).toEqual({
      client_run_id: "BBBBBBBBBBBBBBBB",
      started_at: new Date(NOW).toISOString(),
      ended_at: new Date(NOW + 60000).toISOString(),
      chapter_count: 1,
      choice_count: 2,
      ending_label: "ending_good",
    });
    expect(calls[0].payload.choices.map((c) => c.seq)).toEqual([0, 1]);
    expect(calls[0].keepalive).toBe(false);
  });

  it("重复 finish / finish 之后再记选择都是空操作（同一 clientRunId 只发一次）", async () => {
    const { calls, send } = collectingSender();
    setPlaytestSender(send);
    const session = startPlaytestSession({
      projectId: "p1",
      startedAt: NOW,
      crypto: { getRandomValues: (b) => b.fill(2) },
    });
    session?.addChoice({ menuId: "menu_1", choiceIndex: 1 });
    session?.finish({ endedAt: NOW });
    session?.finish({ endedAt: NOW });
    session?.addChoice({ menuId: "menu_1", choiceIndex: 7 });
    session?.markChapter("ch9");
    await settle();

    expect(calls).toHaveLength(1);
    expect(calls[0].payload.choices).toHaveLength(1);
    expect(calls[0].payload.run.chapter_count).toBe(0);
    expect(session?.finished).toBe(true);
  });

  it("markChapter 会算进 chapter_count（试玩器一次只演一章）", async () => {
    const { calls, send } = collectingSender();
    setPlaytestSender(send);
    const session = startPlaytestSession({
      projectId: "p1",
      startedAt: NOW,
      crypto: { getRandomValues: (b) => b.fill(3) },
    });
    session?.markChapter("ch1");
    session?.markChapter("ch1");
    session?.markChapter("ch2");
    session?.finish({ endedAt: NOW });
    await settle();
    expect(calls[0].payload.run.chapter_count).toBe(2);
  });

  it("没开采集（403 telemetry_disabled）时：不抛错、停止后续上报", async () => {
    setPlaytestSender(() => Promise.resolve("disabled"));
    const first = startPlaytestSession({
      projectId: "p1",
      startedAt: NOW,
      crypto: { getRandomValues: (b) => b.fill(4) },
    });
    first?.addChoice({ menuId: "menu_1", choiceIndex: 0 });
    first?.finish({ endedAt: NOW });
    await settle();
    expect(isPlaytestTelemetryDisabled()).toBe(true);

    const { calls, send } = collectingSender();
    setPlaytestSender(send);
    const second = startPlaytestSession({
      projectId: "p1",
      startedAt: NOW,
      crypto: { getRandomValues: (b) => b.fill(5) },
    });
    second?.addChoice({ menuId: "menu_1", choiceIndex: 0 });
    second?.finish({ endedAt: NOW });
    await settle();
    expect(calls).toHaveLength(0);
  });

  it("每次试玩用不同的 clientRunId（重播是新的一次样本）", () => {
    const { send } = collectingSender();
    setPlaytestSender(send);
    const a = startPlaytestSession({ projectId: "p1" });
    const b = startPlaytestSession({ projectId: "p1" });
    expect(a?.clientRunId).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(b?.clientRunId).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(a?.clientRunId).not.toBe(b?.clientRunId);
    a?.finish({ endedAt: NOW });
    b?.finish({ endedAt: NOW });
  });
});
