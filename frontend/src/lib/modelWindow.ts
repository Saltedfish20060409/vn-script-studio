/**
 * 「模型上下文窗口」这个设置项的输入口径（纯函数，便于单测）。
 *
 * 为什么需要用户填：上下文预算要按**模型窗口**夹一次——撑爆窗口时上游直接拒答，
 * 用户什么都拿不到（比截断严重得多）。而预设表收不全（自建端点、自部署模型、
 * 厂商新名字），服务端只能按保守假设（128k）处理。真知道窗口的是用户自己。
 *
 * 三条规则：
 * 1. **留空 = 自动**（按预设表 / 服务端保守假设）；填 `0` 与留空等价。
 * 2. 只接受**正整数**（千 token），上限 10000（填错一个天文数字不该把预算打穿）。
 * 3. 已知模型时，声明值只能**调低**不能调高（超不过厂商窗口）——提示文案要说清这一点。
 */

export type WindowInput = {
  /** 交给后端的值：0 = 自动 */
  value: number;
  /** 非空表示输入不合法（界面显示、并且不要发出去） */
  error: string;
};

const MAX_K = 10_000;

export function parseWindowK(input: string): WindowInput {
  const raw = (input ?? "").trim();
  if (!raw) return { value: 0, error: "" };
  // 只认十进制数字：`32k`、`3.2万`、`-1`（不夹要走服务端开关）都不在这里处理，
  // 含糊地"帮用户猜"比直接说清楚更容易出错。
  if (!/^\d+$/.test(raw)) {
    return { value: 0, error: "只填数字（单位：千 token），例如 128 表示 128k 上下文" };
  }
  const value = Number(raw);
  if (value <= 0) return { value: 0, error: "" };
  if (value > MAX_K) {
    return { value: MAX_K, error: `太大（上限 ${MAX_K} 千 token），已按上限处理` };
  }
  return { value, error: "" };
}

/** 设置项下面那句提示：把"这个值会怎么被用"讲清楚。 */
export function windowHintText(opts: {
  /** 预设表里该模型的窗口（千 token）；没有就是未知模型 */
  presetK?: number | null;
  /** 当前输入框里的值 */
  declaredK: number;
  /** 本机存储模式下这个设置不生效（它是账号级设置） */
  localStorage?: boolean;
}): string {
  if (opts.localStorage) {
    return "这条只在「加密保存到账号」模式下生效：窗口是账号级的（与设备无关），本机存储不带它。";
  }
  if (opts.declaredK > 0) {
    if (opts.presetK && opts.presetK > 0) {
      return opts.declaredK < opts.presetK
        ? `已声明 ${opts.declaredK}k；该模型预设是 ${opts.presetK}k，声明值更小，会按 ${opts.declaredK}k 夹。`
        : `已声明 ${opts.declaredK}k；但该模型预设是 ${opts.presetK}k，实际按较小的 ${opts.presetK}k 夹（声明只能调低，不能超过厂商窗口）。`;
    }
    return `已声明 ${opts.declaredK}k：自定义模型会按这个值夹上下文（不再用服务端的保守假设）。`;
  }
  if (opts.presetK && opts.presetK > 0) {
    return `留空 = 自动：当前模型按预设 ${opts.presetK}k 处理。自建端点/没收录的模型填一下更保险。`;
  }
  return "留空 = 自动：没收录的模型按服务端的保守假设（默认 128k）处理；填实际窗口可以避免「撑爆上下文」导致上游拒答。";
}

/** 从设置接口的响应里读声明值（缺字段/非法一律当"没声明"）。 */
export function readDeclaredK(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value ?? 0);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.min(MAX_K, Math.floor(n));
}
