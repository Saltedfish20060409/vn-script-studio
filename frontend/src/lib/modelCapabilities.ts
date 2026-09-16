/**
 * 模型能力标记（目前只有一项：能不能用 JSON 模式 / 结构化输出）。
 *
 * 为什么需要：站内预设里有的档位不支持 `response_format={"type":"json_object"}`，
 * 而续写、审稿、Agent 多步循环都依赖模型返回 JSON。后端出站时会按同一套判断把
 * 这个参数拿掉（见 backend/app/core/model_presets.py 的 supports_json_mode），
 * 这里负责在设置页把话说在前面，别让用户选完才发现不稳。
 *
 * 认不出来的一律当作"支持"：预设只帮忙填端点，用户完全可能手填没收录的模型名。
 */

export type PresetLike = {
  id?: string;
  model?: string;
  json_mode?: boolean;
};

export function supportsJsonMode(presets: PresetLike[], model: string): boolean {
  const name = (model || "").trim().toLowerCase();
  if (!name) return true;
  const rows = presets || [];
  const exact = rows.find((p) => (p.model || "").trim().toLowerCase() === name);
  if (exact) return exact.json_mode !== false;
  // 手填简写（如 claude、gpt）时按前缀兜底，和后端保持一致的宽松度
  const prefixed = rows.find((p) => {
    const m = (p.model || "").trim().toLowerCase();
    return Boolean(m) && (name.startsWith(m) || m.startsWith(name));
  });
  if (prefixed) return prefixed.json_mode !== false;
  return true;
}

/** 不支持时给一句人话；支持则返回空串（调用方据此决定要不要渲染）。 */
export function jsonModeWarning(presets: PresetLike[], model: string): string {
  return supportsJsonMode(presets, model)
    ? ""
    : "该档位不支持结构化输出（JSON 模式）：续写、审稿、Agent 等步骤会退化成靠提示词要求 JSON，稳定性不如其它档位，建议换一档。";
}
